# ============================================================================
# SYSTEM GUARDIAN
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - Distributed systems recovery engine
# PURPOSE: Ordered-phase sweep pipeline for task/stage/job recovery
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: SystemGuardian, GuardianConfig, SweepResult, PhaseResult
# DEPENDENCIES: guardian_repository, service_bus, core.models
# ============================================================================
"""
SystemGuardian - Distributed systems recovery engine.

Replaces 3 independent janitor timer triggers with a single ordered-phase sweep.
Runs every 5 minutes from the orchestrator Function App.

Sweep phases (ordered, fail-open):
    Phase 1: Task Recovery   - orphaned pending/queued, stale processing/docker
    Phase 2: Stage Recovery  - zombie stages (Risk H fix)
    Phase 3: Job Recovery    - failed tasks, stuck queued, ancient stale
    Phase 4: Consistency     - orphaned tasks (parent job missing)

Each phase catches exceptions independently (fail-open) so one phase failure
does not block subsequent phases.

Exports:
    SystemGuardian: Main sweep engine
    GuardianConfig: Frozen configuration dataclass
    SweepResult: Sweep outcome with per-phase breakdown
    PhaseResult: Single phase outcome
"""

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.defaults import TaskRoutingDefaults, QueueDefaults
from core.schema.queue import TaskQueueMessage, StageCompleteMessage

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(frozen=True)
class GuardianConfig:
    """
    Frozen configuration for SystemGuardian sweep behaviour.

    All values have sensible defaults. Override via GUARDIAN_* environment
    variables for deployment tuning.
    """

    sweep_interval_minutes: int = 5
    pending_task_timeout_minutes: int = 2
    queued_task_timeout_minutes: int = 5
    processing_task_timeout_minutes: int = 30
    docker_task_timeout_minutes: int = 180  # 3 hours
    stuck_queued_job_timeout_minutes: int = 10
    ancient_job_timeout_minutes: int = 360  # 6 hours
    max_task_retries: int = 3
    enabled: bool = True

    @classmethod
    def from_environment(cls) -> 'GuardianConfig':
        """
        Build config from GUARDIAN_* environment variables, falling back to defaults.

        Environment variables:
            GUARDIAN_SWEEP_INTERVAL_MINUTES
            GUARDIAN_PENDING_TASK_TIMEOUT_MINUTES
            GUARDIAN_QUEUED_TASK_TIMEOUT_MINUTES
            GUARDIAN_PROCESSING_TASK_TIMEOUT_MINUTES
            GUARDIAN_DOCKER_TASK_TIMEOUT_MINUTES
            GUARDIAN_STUCK_QUEUED_JOB_TIMEOUT_MINUTES
            GUARDIAN_ANCIENT_JOB_TIMEOUT_MINUTES
            GUARDIAN_MAX_TASK_RETRIES
            GUARDIAN_ENABLED
        """
        defaults = cls()
        return cls(
            sweep_interval_minutes=int(os.environ.get(
                'GUARDIAN_SWEEP_INTERVAL_MINUTES',
                defaults.sweep_interval_minutes
            )),
            pending_task_timeout_minutes=int(os.environ.get(
                'GUARDIAN_PENDING_TASK_TIMEOUT_MINUTES',
                defaults.pending_task_timeout_minutes
            )),
            queued_task_timeout_minutes=int(os.environ.get(
                'GUARDIAN_QUEUED_TASK_TIMEOUT_MINUTES',
                defaults.queued_task_timeout_minutes
            )),
            processing_task_timeout_minutes=int(os.environ.get(
                'GUARDIAN_PROCESSING_TASK_TIMEOUT_MINUTES',
                defaults.processing_task_timeout_minutes
            )),
            docker_task_timeout_minutes=int(os.environ.get(
                'GUARDIAN_DOCKER_TASK_TIMEOUT_MINUTES',
                defaults.docker_task_timeout_minutes
            )),
            stuck_queued_job_timeout_minutes=int(os.environ.get(
                'GUARDIAN_STUCK_QUEUED_JOB_TIMEOUT_MINUTES',
                defaults.stuck_queued_job_timeout_minutes
            )),
            ancient_job_timeout_minutes=int(os.environ.get(
                'GUARDIAN_ANCIENT_JOB_TIMEOUT_MINUTES',
                defaults.ancient_job_timeout_minutes
            )),
            max_task_retries=int(os.environ.get(
                'GUARDIAN_MAX_TASK_RETRIES',
                defaults.max_task_retries
            )),
            enabled=os.environ.get(
                'GUARDIAN_ENABLED', str(defaults.enabled)
            ).lower() in ('true', '1', 'yes'),
        )


# ============================================================================
# RESULT DATACLASSES
# ============================================================================

@dataclass
class PhaseResult:
    """Outcome of a single sweep phase."""

    phase: str
    scanned: int = 0
    fixed: int = 0
    actions: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class SweepResult:
    """
    Complete outcome of a guardian sweep.

    Tracks per-phase results, timing, and aggregate counts.
    """

    sweep_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    phases: Dict[str, PhaseResult] = field(default_factory=dict)
    total_scanned: int = 0
    total_fixed: int = 0
    success: bool = True
    error: Optional[str] = None

    def complete(self) -> None:
        """Finalize the sweep result with totals and timestamp."""
        self.completed_at = datetime.now(timezone.utc)
        self.total_scanned = sum(p.scanned for p in self.phases.values())
        self.total_fixed = sum(p.fixed for p in self.phases.values())
        # Success if no phase had a fatal error
        self.success = all(p.error is None for p in self.phases.values())

    @property
    def all_actions(self) -> List[str]:
        """Flat list of all actions across all phases."""
        actions = []
        for phase_result in self.phases.values():
            actions.extend(phase_result.actions)
        return actions

    @property
    def phases_dict(self) -> Dict[str, Any]:
        """Serializable dict of phase results for audit logging."""
        result = {}
        for name, phase_result in self.phases.items():
            result[name] = {
                'scanned': phase_result.scanned,
                'fixed': phase_result.fixed,
                'actions': phase_result.actions,
                'error': phase_result.error,
            }
        return result


# ============================================================================
# SYSTEM GUARDIAN
# ============================================================================

class SystemGuardian:
    """
    Distributed systems recovery engine.

    Runs an ordered 4-phase sweep to detect and fix anomalies in the
    job/task lifecycle. Each phase is fail-open: exceptions are caught
    and stored in PhaseResult.error without blocking subsequent phases.

    Args:
        repo: GuardianRepository instance for DB operations.
        queue_client: ServiceBusRepository instance for queue operations.
        config: Optional GuardianConfig (defaults to GuardianConfig()).
    """

    def __init__(self, repo, queue_client, config=None):
        self._repo = repo
        self._queue = queue_client
        self._config = config or GuardianConfig()
        self._docker_task_types = list(TaskRoutingDefaults.DOCKER_TASKS)

    # ================================================================
    # PUBLIC API
    # ================================================================

    def sweep(self) -> SweepResult:
        """
        Execute the full 4-phase guardian sweep.

        Returns:
            SweepResult with per-phase breakdown.
        """
        result = SweepResult()

        # Check enabled
        if not self._config.enabled:
            logger.info("[GUARDIAN] Sweep disabled by config")
            result.error = "disabled"
            result.success = False
            result.completed_at = datetime.now(timezone.utc)
            return result

        # Check schema readiness
        if not self._repo.schema_ready():
            logger.info("[GUARDIAN] Schema not ready, skipping sweep")
            result.error = "schema_not_ready"
            result.success = False
            result.completed_at = datetime.now(timezone.utc)
            return result

        # Two-phase audit: log start
        self._repo.log_sweep_start(result.sweep_id, result.started_at)

        logger.info(
            f"[GUARDIAN] Sweep {result.sweep_id[:8]}... starting "
            f"(4 phases, fail-open)"
        )

        # Phase 1: Task Recovery
        try:
            result.phases['task_recovery'] = self._phase_task_recovery()
        except Exception as e:
            logger.error(f"[GUARDIAN] Phase 1 (task_recovery) failed: {e}")
            result.phases['task_recovery'] = PhaseResult(
                phase='task_recovery', error=str(e)
            )

        # Phase 2: Stage Recovery
        try:
            result.phases['stage_recovery'] = self._phase_stage_recovery()
        except Exception as e:
            logger.error(f"[GUARDIAN] Phase 2 (stage_recovery) failed: {e}")
            result.phases['stage_recovery'] = PhaseResult(
                phase='stage_recovery', error=str(e)
            )

        # Phase 3: Job Recovery
        try:
            result.phases['job_recovery'] = self._phase_job_recovery()
        except Exception as e:
            logger.error(f"[GUARDIAN] Phase 3 (job_recovery) failed: {e}")
            result.phases['job_recovery'] = PhaseResult(
                phase='job_recovery', error=str(e)
            )

        # Phase 4: Consistency
        try:
            result.phases['consistency'] = self._phase_consistency()
        except Exception as e:
            logger.error(f"[GUARDIAN] Phase 4 (consistency) failed: {e}")
            result.phases['consistency'] = PhaseResult(
                phase='consistency', error=str(e)
            )

        # Finalize
        result.complete()

        logger.info(
            f"[GUARDIAN] Sweep {result.sweep_id[:8]}... completed: "
            f"scanned={result.total_scanned}, fixed={result.total_fixed}, "
            f"success={result.success}"
        )

        # Two-phase audit: log end
        status = 'completed' if result.success else 'partial'
        self._repo.log_sweep_end(
            sweep_id=result.sweep_id,
            completed_at=result.completed_at,
            items_scanned=result.total_scanned,
            items_fixed=result.total_fixed,
            actions_taken=[{'action': a} for a in result.all_actions],
            phases=result.phases_dict,
            status=status,
            error_details=result.error,
        )

        return result

    # ================================================================
    # PHASE 1: TASK RECOVERY
    # ================================================================

    def _phase_task_recovery(self) -> PhaseResult:
        """
        Recover orphaned and stale tasks.

        Sub-phases:
            1a: Orphaned PENDING tasks (message lost before queuing)
            1b: Orphaned QUEUED tasks (message lost from queue)
            1c: Stale PROCESSING tasks (Function App, excludes Docker)
            1d: Stale Docker tasks (long-running, mark FAILED directly)
        """
        phase = PhaseResult(phase='task_recovery')

        # 1a: Orphaned PENDING tasks
        pending_tasks = self._repo.get_orphaned_pending_tasks(
            timeout_minutes=self._config.pending_task_timeout_minutes
        )
        phase.scanned += len(pending_tasks)
        for task in pending_tasks:
            self._recover_orphaned_task(task, phase)

        # 1b: Orphaned QUEUED tasks
        queued_tasks = self._repo.get_orphaned_queued_tasks(
            timeout_minutes=self._config.queued_task_timeout_minutes
        )
        phase.scanned += len(queued_tasks)
        for task in queued_tasks:
            self._recover_queued_task(task, phase)

        # 1c: Stale PROCESSING tasks (exclude Docker types)
        stale_tasks = self._repo.get_stale_processing_tasks(
            timeout_minutes=self._config.processing_task_timeout_minutes,
            exclude_types=self._docker_task_types,
        )
        phase.scanned += len(stale_tasks)
        for task in stale_tasks:
            self._recover_stale_processing_task(task, phase)

        # 1d: Stale Docker tasks
        docker_tasks = self._repo.get_stale_docker_tasks(
            timeout_minutes=self._config.docker_task_timeout_minutes,
            docker_types=self._docker_task_types,
        )
        phase.scanned += len(docker_tasks)
        for task in docker_tasks:
            task_id = task['task_id']
            logger.info(
                f"[GUARDIAN] Docker task {task_id[:16]}... stale "
                f"(>{self._config.docker_task_timeout_minutes}min), marking FAILED"
            )
            self._repo.mark_tasks_failed(
                [task_id],
                f"guardian_docker_timeout: stale >{self._config.docker_task_timeout_minutes}min"
            )
            phase.fixed += 1
            phase.actions.append(f"docker_task_failed:{task_id[:16]}")

        return phase

    def _recover_orphaned_task(self, task: Dict[str, Any], phase: PhaseResult) -> None:
        """
        Recover an orphaned PENDING task by re-sending its queue message.

        If retry_count >= max_task_retries, marks FAILED instead.
        """
        task_id = task['task_id']
        retry_count = task.get('retry_count', 0)

        if retry_count >= self._config.max_task_retries:
            logger.info(
                f"[GUARDIAN] Orphaned PENDING task {task_id[:16]}... "
                f"max retries ({retry_count}), marking FAILED"
            )
            self._repo.mark_tasks_failed(
                [task_id],
                f"guardian_max_retries: {retry_count} retries exhausted"
            )
            phase.fixed += 1
            phase.actions.append(f"pending_task_failed_max_retries:{task_id[:16]}")
            return

        # Re-send message
        logger.info(
            f"[GUARDIAN] Re-sending orphaned PENDING task {task_id[:16]}... "
            f"(retry {retry_count + 1})"
        )
        self._repo.increment_task_retry(task_id)
        self._send_task_message(task)
        phase.fixed += 1
        phase.actions.append(f"pending_task_resent:{task_id[:16]}")

    def _recover_queued_task(self, task: Dict[str, Any], phase: PhaseResult) -> None:
        """
        Recover an orphaned QUEUED task.

        First peeks the queue to verify the message is truly lost.
        If message exists, skips (task is just waiting in backlog).
        Otherwise re-sends or marks FAILED based on retry count.
        """
        task_id = task['task_id']
        task_type = task.get('task_type', '')
        queue_name = self._get_queue_for_task(task_type)

        # Peek queue first
        message_exists = self._queue.message_exists_for_task(queue_name, task_id)
        if message_exists:
            logger.debug(
                f"[GUARDIAN] QUEUED task {task_id[:16]}... "
                f"message found in queue, skipping"
            )
            return

        retry_count = task.get('retry_count', 0)
        if retry_count >= self._config.max_task_retries:
            logger.info(
                f"[GUARDIAN] Orphaned QUEUED task {task_id[:16]}... "
                f"max retries ({retry_count}), marking FAILED"
            )
            self._repo.mark_tasks_failed(
                [task_id],
                f"guardian_max_retries: {retry_count} retries exhausted (queued)"
            )
            phase.fixed += 1
            phase.actions.append(f"queued_task_failed_max_retries:{task_id[:16]}")
            return

        # Re-send
        logger.info(
            f"[GUARDIAN] Re-sending orphaned QUEUED task {task_id[:16]}... "
            f"(retry {retry_count + 1})"
        )
        self._repo.increment_task_retry(task_id)
        self._send_task_message(task)
        phase.fixed += 1
        phase.actions.append(f"queued_task_resent:{task_id[:16]}")

    def _recover_stale_processing_task(
        self, task: Dict[str, Any], phase: PhaseResult
    ) -> None:
        """
        Recover a stale PROCESSING task.

        Logic:
            - last_pulse is None AND retry_count < max → re-queue (never started)
            - last_pulse is not None OR retry_count >= max → mark FAILED
        """
        task_id = task['task_id']
        last_pulse = task.get('last_pulse')
        retry_count = task.get('retry_count', 0)

        if last_pulse is None and retry_count < self._config.max_task_retries:
            # Task never started processing, re-queue it
            logger.info(
                f"[GUARDIAN] Stale PROCESSING task {task_id[:16]}... "
                f"(no pulse, retry {retry_count + 1}), re-queuing"
            )
            self._repo.increment_task_retry(task_id)
            self._send_task_message(task)
            phase.fixed += 1
            phase.actions.append(f"stale_task_requeued:{task_id[:16]}")
        else:
            # Task ran and died, or max retries exceeded
            reason = "task_ran_and_died" if last_pulse else "max_retries"
            logger.info(
                f"[GUARDIAN] Stale PROCESSING task {task_id[:16]}... "
                f"({reason}), marking FAILED"
            )
            self._repo.mark_tasks_failed(
                [task_id],
                f"guardian_stale_processing: {reason} "
                f"(pulse={'yes' if last_pulse else 'no'}, retries={retry_count})"
            )
            phase.fixed += 1
            phase.actions.append(f"stale_task_failed:{task_id[:16]}")

    # ================================================================
    # PHASE 2: STAGE RECOVERY (Risk H fix)
    # ================================================================

    def _phase_stage_recovery(self) -> PhaseResult:
        """
        Recover zombie stages where all tasks are terminal but the
        stage hasn't advanced.

        If any failed tasks → mark job FAILED with partial results.
        If all tasks completed → re-send StageCompleteMessage.
        """
        phase = PhaseResult(phase='stage_recovery')

        zombies = self._repo.get_zombie_stages()
        phase.scanned += len(zombies)

        for job in zombies:
            job_id = job['job_id']
            failed_tasks = job.get('failed_tasks', 0)

            if failed_tasks > 0:
                # Has failures → mark job FAILED
                logger.info(
                    f"[GUARDIAN] Zombie stage for job {job_id[:16]}... "
                    f"has {failed_tasks} failed tasks, marking job FAILED"
                )
                partial = self._build_partial_results(job_id, job)
                self._repo.mark_job_failed(
                    job_id,
                    f"guardian_zombie_stage: {failed_tasks} task(s) failed at stage {job.get('stage')}",
                    partial_results=partial,
                )
                phase.fixed += 1
                phase.actions.append(f"zombie_job_failed:{job_id[:16]}")
            else:
                # All tasks completed → re-attempt stage advancement
                logger.info(
                    f"[GUARDIAN] Zombie stage for job {job_id[:16]}... "
                    f"all tasks completed, re-sending StageCompleteMessage"
                )
                self._send_stage_complete_message(job)
                phase.fixed += 1
                phase.actions.append(f"zombie_stage_advanced:{job_id[:16]}")

        return phase

    # ================================================================
    # PHASE 3: JOB RECOVERY
    # ================================================================

    def _phase_job_recovery(self) -> PhaseResult:
        """
        Recover stuck and failed jobs.

        Sub-phases:
            3a: PROCESSING jobs with failed tasks
            3b: Stuck QUEUED jobs (no tasks created)
            3c: Ancient stale PROCESSING jobs (hard backstop)
        """
        phase = PhaseResult(phase='job_recovery')

        # 3a: Jobs with failed tasks
        failed_jobs = self._repo.get_jobs_with_failed_tasks()
        phase.scanned += len(failed_jobs)
        for job in failed_jobs:
            job_id = job['job_id']
            failed_count = job.get('failed_count', 0)
            # Only mark FAILED if no tasks are still in progress
            processing = job.get('processing_count', 0)
            queued = job.get('queued_count', 0)
            if processing > 0 or queued > 0:
                logger.debug(
                    f"[GUARDIAN] Job {job_id[:16]}... has failed tasks "
                    f"but {processing} processing + {queued} queued, skipping"
                )
                continue

            logger.info(
                f"[GUARDIAN] Job {job_id[:16]}... has {failed_count} failed tasks, "
                f"marking FAILED"
            )
            partial = self._build_partial_results(job_id, job)
            self._repo.mark_job_failed(
                job_id,
                f"guardian_failed_tasks: {failed_count} task(s) failed",
                partial_results=partial,
            )
            phase.fixed += 1
            phase.actions.append(f"job_failed_tasks:{job_id[:16]}")

        # 3b: Stuck QUEUED jobs
        stuck_jobs = self._repo.get_stuck_queued_jobs(
            timeout_minutes=self._config.stuck_queued_job_timeout_minutes
        )
        phase.scanned += len(stuck_jobs)
        for job in stuck_jobs:
            job_id = job['job_id']
            logger.info(
                f"[GUARDIAN] Stuck QUEUED job {job_id[:16]}... "
                f"(>{self._config.stuck_queued_job_timeout_minutes}min, no tasks), "
                f"marking FAILED"
            )
            self._repo.mark_job_failed(
                job_id,
                f"guardian_stuck_queued: no tasks created after "
                f"{self._config.stuck_queued_job_timeout_minutes}min"
            )
            phase.fixed += 1
            phase.actions.append(f"stuck_queued_job_failed:{job_id[:16]}")

        # 3c: Ancient stale jobs
        ancient_jobs = self._repo.get_ancient_stale_jobs(
            timeout_minutes=self._config.ancient_job_timeout_minutes
        )
        phase.scanned += len(ancient_jobs)
        for job in ancient_jobs:
            job_id = job['job_id']
            logger.info(
                f"[GUARDIAN] Ancient stale job {job_id[:16]}... "
                f"(>{self._config.ancient_job_timeout_minutes}min), marking FAILED"
            )
            partial = self._build_partial_results(job_id, job)
            self._repo.mark_job_failed(
                job_id,
                f"guardian_ancient_stale: processing >{self._config.ancient_job_timeout_minutes}min",
                partial_results=partial,
            )
            phase.fixed += 1
            phase.actions.append(f"ancient_job_failed:{job_id[:16]}")

        return phase

    # ================================================================
    # PHASE 4: CONSISTENCY
    # ================================================================

    def _phase_consistency(self) -> PhaseResult:
        """
        Find and fix orphaned tasks whose parent job is missing.
        """
        phase = PhaseResult(phase='consistency')

        orphans = self._repo.get_orphaned_tasks()
        phase.scanned += len(orphans)

        if orphans:
            task_ids = [t['task_id'] for t in orphans]
            logger.info(
                f"[GUARDIAN] Marking {len(task_ids)} orphaned tasks FAILED "
                f"(parent_job_missing)"
            )
            self._repo.mark_tasks_failed(task_ids, "guardian_consistency: parent_job_missing")
            phase.fixed += len(task_ids)
            for tid in task_ids:
                phase.actions.append(f"orphan_task_failed:{tid[:16]}")

        return phase

    # ================================================================
    # HELPERS
    # ================================================================

    def _get_queue_for_task(self, task_type: str) -> str:
        """Route task_type to the appropriate queue name."""
        if task_type in TaskRoutingDefaults.DOCKER_TASKS:
            return QueueDefaults.CONTAINER_TASKS_QUEUE
        return QueueDefaults.JOBS_QUEUE

    def _send_task_message(self, task: Dict[str, Any]) -> None:
        """Build a TaskQueueMessage from a task dict and send to queue."""
        task_type = task.get('task_type', '')
        queue_name = self._get_queue_for_task(task_type)

        msg = TaskQueueMessage(
            task_id=task['task_id'],
            parent_job_id=task['parent_job_id'],
            job_type=task['job_type'],
            task_type=task_type,
            stage=task['stage'],
            task_index=task.get('task_index', '0'),
            parameters=task.get('parameters', {}),
            retry_count=task.get('retry_count', 0),
        )
        self._queue.send_message(queue_name, msg)

    def _send_stage_complete_message(self, job: Dict[str, Any]) -> None:
        """Build and send a StageCompleteMessage for zombie stage recovery."""
        msg = StageCompleteMessage(
            job_id=job['job_id'],
            job_type=job['job_type'],
            completed_stage=job['stage'],
            completed_at=datetime.now(timezone.utc).isoformat(),
            completed_by_app="system_guardian",
            correlation_id=str(uuid.uuid4())[:8],
        )
        self._queue.send_message(QueueDefaults.JOBS_QUEUE, msg)

    def _build_partial_results(
        self, job_id: str, job_info: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Query completed task results for partial result capture.

        Non-fatal: returns None on any error.
        """
        try:
            completed = self._repo.get_completed_task_results(job_id)
            if not completed:
                return None

            return {
                'status': 'partial',
                'completed_tasks': len(completed),
                'total_stages': job_info.get('total_stages'),
                'failed_at_stage': job_info.get('stage'),
                'partial_results': [
                    {
                        'task_id': t['task_id'],
                        'task_type': t.get('task_type'),
                        'stage': t.get('stage'),
                        'result_data': t.get('result_data'),
                    }
                    for t in completed[:10]  # Truncate to 10
                ],
                'recovered_by': 'system_guardian',
            }
        except Exception as e:
            logger.warning(
                f"[GUARDIAN] Failed to build partial results for {job_id[:16]}...: {e}"
            )
            return None


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'SystemGuardian',
    'GuardianConfig',
    'SweepResult',
    'PhaseResult',
]
