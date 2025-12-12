"""
Janitor Service - Maintenance Business Logic.

Coordinates janitor operations between timer triggers and the repository:
    Task Watchdog: Detect and fix stale PROCESSING tasks
    Job Health Monitor: Detect jobs with failed tasks, capture partial results
    Orphan Detector: Find and handle orphaned tasks and zombie jobs

This service runs via standalone timer triggers (not CoreMachine).

Exports:
    JanitorService: Maintenance operations coordinator
    JanitorConfig: Configuration dataclass
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os

from infrastructure.janitor_repository import JanitorRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "JanitorService")


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class JanitorConfig:
    """
    Janitor configuration with sensible defaults.

    All values can be overridden via environment variables.
    """

    # Task watchdog settings
    task_timeout_minutes: int = 30  # Azure Functions max is 10-30 min

    # Job health settings
    job_stale_hours: int = 24  # Jobs shouldn't take more than a day

    # Orphan detector settings
    queued_timeout_hours: int = 1  # Jobs should start processing within an hour

    # Master switch
    enabled: bool = True

    @classmethod
    def from_environment(cls) -> "JanitorConfig":
        """Load configuration from environment variables."""
        return cls(
            task_timeout_minutes=int(os.environ.get("JANITOR_TASK_TIMEOUT_MINUTES", "30")),
            job_stale_hours=int(os.environ.get("JANITOR_JOB_STALE_HOURS", "24")),
            queued_timeout_hours=int(os.environ.get("JANITOR_QUEUED_TIMEOUT_HOURS", "1")),
            enabled=os.environ.get("JANITOR_ENABLED", "true").lower() == "true"
        )


# ============================================================================
# RESULT MODELS
# ============================================================================

@dataclass
class JanitorRunResult:
    """Result of a janitor run."""

    run_type: str
    success: bool
    items_scanned: int = 0
    items_fixed: int = 0
    actions_taken: List[Dict[str, Any]] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    run_id: Optional[str] = None

    def complete(self, success: bool = True, error: Optional[str] = None):
        """Mark the run as complete."""
        self.completed_at = datetime.now(timezone.utc)
        self.success = success
        self.error = error

    @property
    def duration_ms(self) -> int:
        """Get run duration in milliseconds."""
        if self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "run_type": self.run_type,
            "success": self.success,
            "items_scanned": self.items_scanned,
            "items_fixed": self.items_fixed,
            "actions_taken": self.actions_taken,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "run_id": self.run_id
        }


# ============================================================================
# JANITOR SERVICE
# ============================================================================

class JanitorService:
    """
    Janitor service for system maintenance operations.

    Provides three main operations:
    1. run_task_watchdog(): Detect and fix stale PROCESSING tasks
    2. run_job_health_check(): Detect and fix jobs with failed tasks
    3. run_orphan_detection(): Detect and handle orphaned records

    Usage:
        service = JanitorService()

        # From timer trigger
        result = service.run_task_watchdog()
        print(f"Fixed {result.items_fixed} stale tasks")
    """

    def __init__(
        self,
        config: Optional[JanitorConfig] = None,
        repository: Optional[JanitorRepository] = None
    ):
        """
        Initialize janitor service.

        Args:
            config: Janitor configuration (defaults from environment)
            repository: Janitor repository (created if not provided)
        """
        self.config = config or JanitorConfig.from_environment()
        self.repo = repository or JanitorRepository()
        logger.info(
            f"JanitorService initialized: enabled={self.config.enabled}, "
            f"task_timeout={self.config.task_timeout_minutes}min, "
            f"job_stale={self.config.job_stale_hours}h"
        )

    # ========================================================================
    # TASK WATCHDOG
    # ========================================================================

    def run_task_watchdog(self) -> JanitorRunResult:
        """
        Detect and fix stale PROCESSING tasks.

        Tasks stuck in PROCESSING state beyond the configured timeout
        (default 30 minutes) are marked as FAILED with an error message.

        Returns:
            JanitorRunResult with statistics and actions taken
        """
        result = JanitorRunResult(run_type="task_watchdog", success=False)
        logger.debug("[JANITOR] task_watchdog: Creating JanitorRunResult object")

        # Create audit record FIRST before doing any work
        result.run_id = self._start_run(result)
        logger.debug(f"[JANITOR] task_watchdog: Audit record created with run_id={result.run_id}")

        if not self.config.enabled:
            logger.info("[JANITOR] Janitor disabled via configuration - skipping task watchdog")
            logger.debug("[JANITOR] task_watchdog: JANITOR_ENABLED=false, returning early")
            result.complete(success=True)
            self._complete_run(result)
            return result

        try:
            logger.info(
                f"[JANITOR] Starting task watchdog (timeout: {self.config.task_timeout_minutes} min)"
            )
            logger.debug(
                f"[JANITOR] task_watchdog: Querying for tasks with status='PROCESSING' "
                f"AND updated_at < NOW() - INTERVAL '{self.config.task_timeout_minutes} minutes'"
            )

            # Find stale tasks
            stale_tasks = self.repo.get_stale_processing_tasks(
                timeout_minutes=self.config.task_timeout_minutes
            )
            result.items_scanned = len(stale_tasks)
            logger.debug(f"[JANITOR] task_watchdog: Query returned {len(stale_tasks)} stale tasks")

            if not stale_tasks:
                logger.info("[JANITOR] No stale tasks found - system healthy")
                logger.debug("[JANITOR] task_watchdog: No stale tasks, completing with success=True")
                result.complete(success=True)
                self._complete_run(result)
                return result

            logger.warning(f"[JANITOR] Found {len(stale_tasks)} stale PROCESSING tasks")

            # Log each stale task with full details BEFORE fixing
            for i, task in enumerate(stale_tasks, 1):
                minutes_stuck = round(task.get('minutes_stuck', 0), 1)
                logger.warning(
                    f"[JANITOR] Stale task {i}/{len(stale_tasks)}: "
                    f"task_id={task['task_id']}, "
                    f"job_id={task['parent_job_id'][:16]}..., "
                    f"job_type={task.get('job_type')}, "
                    f"task_type={task.get('task_type')}, "
                    f"stage={task.get('stage')}, "
                    f"stuck_for={minutes_stuck}min, "
                    f"retry_count={task.get('retry_count', 0)}, "
                    f"updated_at={task.get('updated_at')}"
                )

            # Mark tasks as failed
            task_ids = [t['task_id'] for t in stale_tasks]
            logger.debug(f"[JANITOR] task_watchdog: Preparing to mark {len(task_ids)} tasks as FAILED")
            error_message = (
                f"[JANITOR] Silent failure detected - task exceeded "
                f"{self.config.task_timeout_minutes} minute timeout. "
                f"Azure Functions max execution time is 10-30 minutes."
            )
            logger.debug(f"[JANITOR] task_watchdog: Error message: {error_message[:80]}...")

            logger.debug(f"[JANITOR] task_watchdog: Executing batch UPDATE for {len(task_ids)} tasks")
            fixed_count = self.repo.mark_tasks_as_failed(task_ids, error_message)
            result.items_fixed = fixed_count
            logger.debug(f"[JANITOR] task_watchdog: Batch UPDATE completed, {fixed_count} rows affected")

            # Record actions and log each fix
            for task in stale_tasks:
                minutes_stuck = round(task.get('minutes_stuck', 0), 1)
                result.actions_taken.append({
                    "action": "mark_task_failed",
                    "task_id": task['task_id'],
                    "parent_job_id": task['parent_job_id'],
                    "job_type": task.get('job_type'),
                    "task_type": task.get('task_type'),
                    "stage": task.get('stage'),
                    "minutes_stuck": minutes_stuck,
                    "reason": "exceeded_timeout"
                })
                logger.info(
                    f"[JANITOR] Marked task FAILED: task_id={task['task_id']}, "
                    f"job_id={task['parent_job_id'][:16]}..., stuck={minutes_stuck}min"
                )

            logger.warning(f"[JANITOR] Task watchdog complete: marked {fixed_count} stale tasks as FAILED")
            logger.debug(f"[JANITOR] task_watchdog: Success - scanned={result.items_scanned}, fixed={result.items_fixed}")
            result.complete(success=True)

        except Exception as e:
            logger.error(f"[JANITOR] Task watchdog failed: {e}")
            import traceback
            logger.error(f"[JANITOR] Traceback: {traceback.format_exc()}")
            result.complete(success=False, error=str(e))

        logger.debug(f"[JANITOR] task_watchdog: Logging run to janitor_runs table")
        self._complete_run(result)
        logger.debug(f"[JANITOR] task_watchdog: Run complete, returning result")
        return result

    # ========================================================================
    # JOB HEALTH MONITOR
    # ========================================================================

    def run_job_health_check(self) -> JanitorRunResult:
        """
        Check job health and propagate task failures.

        Finds jobs in PROCESSING state that have failed tasks, marks them
        as FAILED, and captures partial results from completed tasks.

        Returns:
            JanitorRunResult with statistics and actions taken
        """
        result = JanitorRunResult(run_type="job_health", success=False)
        logger.debug("[JANITOR] job_health: Creating JanitorRunResult object")

        # Create audit record FIRST before doing any work
        result.run_id = self._start_run(result)
        logger.debug(f"[JANITOR] job_health: Audit record created with run_id={result.run_id}")

        if not self.config.enabled:
            logger.info("[JANITOR] Janitor disabled via configuration - skipping job health check")
            logger.debug("[JANITOR] job_health: JANITOR_ENABLED=false, returning early")
            result.complete(success=True)
            self._complete_run(result)
            return result

        try:
            logger.info("[JANITOR] Starting job health check")
            logger.debug(
                "[JANITOR] job_health: Querying for jobs with status='PROCESSING' "
                "that have at least one task with status='FAILED'"
            )

            # Find jobs with failed tasks
            failed_jobs = self.repo.get_processing_jobs_with_failed_tasks()
            result.items_scanned = len(failed_jobs)
            logger.debug(f"[JANITOR] job_health: Query returned {len(failed_jobs)} jobs with failed tasks")

            if not failed_jobs:
                logger.info("[JANITOR] No jobs with failed tasks found - system healthy")
                logger.debug("[JANITOR] job_health: No failed jobs, completing with success=True")
                result.complete(success=True)
                self._complete_run(result)
                return result

            logger.warning(f"[JANITOR] Found {len(failed_jobs)} PROCESSING jobs with failed tasks")

            # Process each failed job
            for i, job in enumerate(failed_jobs, 1):
                job_id = job['job_id']
                job_type = job.get('job_type')
                failed_count = job.get('failed_count', 0)
                completed_count = job.get('completed_count', 0)
                processing_count = job.get('processing_count', 0)
                queued_count = job.get('queued_count', 0)
                total_tasks = job.get('total_tasks', 0)
                failed_task_ids = job.get('failed_task_ids', [])
                failed_errors = job.get('failed_task_errors', [])
                stage = job.get('stage')
                total_stages = job.get('total_stages')

                # Log detailed job info BEFORE fixing
                logger.warning(
                    f"[JANITOR] Failed job {i}/{len(failed_jobs)}: "
                    f"job_id={job_id[:16]}..., "
                    f"job_type={job_type}, "
                    f"stage={stage}/{total_stages}, "
                    f"tasks: {completed_count} completed, {failed_count} failed, "
                    f"{processing_count} processing, {queued_count} queued (total={total_tasks})"
                )

                # Log each failed task ID
                for task_id in failed_task_ids[:10]:  # Limit to first 10
                    logger.warning(f"[JANITOR]   - Failed task: {task_id}")
                if len(failed_task_ids) > 10:
                    logger.warning(f"[JANITOR]   - ... and {len(failed_task_ids) - 10} more failed tasks")

                # Build error message
                error_summary = "; ".join(filter(None, failed_errors[:3]))
                if len(failed_errors) > 3:
                    error_summary += f" ... and {len(failed_errors) - 3} more errors"

                error_details = (
                    f"[JANITOR] Job failed due to {failed_count} task failure(s). "
                    f"Tasks: {completed_count}/{total_tasks} completed. "
                    f"Failed task IDs: {failed_task_ids[:5]}. "
                    f"Errors: {error_summary}"
                )

                # Capture partial results
                partial_results = self._build_partial_results(job_id, job)

                # Mark job as failed
                success = self.repo.mark_job_as_failed(
                    job_id=job_id,
                    error_details=error_details,
                    partial_results=partial_results
                )

                if success:
                    result.items_fixed += 1
                    result.actions_taken.append({
                        "action": "mark_job_failed",
                        "job_id": job_id,
                        "job_type": job_type,
                        "stage": stage,
                        "total_stages": total_stages,
                        "failed_tasks": failed_count,
                        "completed_tasks": completed_count,
                        "total_tasks": total_tasks,
                        "reason": "task_failures"
                    })
                    logger.info(
                        f"[JANITOR] Marked job FAILED: job_id={job_id[:16]}..., "
                        f"job_type={job_type}, failed_tasks={failed_count}"
                    )

            logger.warning(f"[JANITOR] Job health check complete: marked {result.items_fixed} jobs as FAILED")
            logger.debug(f"[JANITOR] job_health: Success - scanned={result.items_scanned}, fixed={result.items_fixed}")
            result.complete(success=True)

        except Exception as e:
            logger.error(f"[JANITOR] Job health check failed: {e}")
            import traceback
            logger.error(f"[JANITOR] Traceback: {traceback.format_exc()}")
            result.complete(success=False, error=str(e))

        logger.debug(f"[JANITOR] job_health: Logging run to janitor_runs table")
        self._complete_run(result)
        logger.debug(f"[JANITOR] job_health: Run complete, returning result")
        return result

    def _build_partial_results(
        self,
        job_id: str,
        job_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build partial results for a failed job.

        Captures what was completed before failure for debugging.

        Args:
            job_id: Job ID
            job_info: Job information from health check query

        Returns:
            Dict with partial results
        """
        try:
            # Get completed task results
            completed_tasks = self.repo.get_completed_task_results_for_job(job_id)

            return {
                "status": "partial_failure",
                "completed_tasks_count": len(completed_tasks),
                "failed_tasks_count": job_info.get('failed_count', 0),
                "total_tasks_count": job_info.get('total_tasks', 0),
                "failed_at_stage": job_info.get('stage'),
                "total_stages": job_info.get('total_stages'),
                "completed_task_ids": [t['task_id'] for t in completed_tasks],
                "failed_task_ids": job_info.get('failed_task_ids', []),
                "partial_results": [
                    {
                        "task_id": t['task_id'],
                        "task_type": t.get('task_type'),
                        "stage": t.get('stage'),
                        "result_data": t.get('result_data')
                    }
                    for t in completed_tasks[:10]  # Limit to 10 results
                ],
                "janitor_cleanup_at": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.warning(f"Failed to build partial results for {job_id}: {e}")
            return {
                "status": "partial_failure",
                "error": f"Failed to capture partial results: {e}"
            }

    # ========================================================================
    # ORPHAN DETECTION
    # ========================================================================

    def run_orphan_detection(self) -> JanitorRunResult:
        """
        Detect and handle orphaned tasks and zombie jobs.

        Detects:
        1. Orphaned tasks (parent job doesn't exist)
        2. Zombie jobs (PROCESSING but all tasks terminal)
        3. Stuck QUEUED jobs (no tasks created after timeout)
        4. Ancient stale jobs (PROCESSING for > 24 hours)

        Returns:
            JanitorRunResult with statistics and actions taken
        """
        result = JanitorRunResult(run_type="orphan_detector", success=False)
        logger.debug("[JANITOR] orphan_detector: Creating JanitorRunResult object")

        # Create audit record FIRST before doing any work
        result.run_id = self._start_run(result)
        logger.debug(f"[JANITOR] orphan_detector: Audit record created with run_id={result.run_id}")

        if not self.config.enabled:
            logger.info("[JANITOR] Janitor disabled via configuration - skipping orphan detection")
            logger.debug("[JANITOR] orphan_detector: JANITOR_ENABLED=false, returning early")
            result.complete(success=True)
            self._complete_run(result)
            return result

        try:
            logger.info("[JANITOR] Starting orphan detection (4 categories)")
            logger.debug("[JANITOR] orphan_detector: Will check: orphaned_tasks, zombie_jobs, stuck_queued, ancient_stale")

            # 1. Find orphaned tasks
            logger.info("[JANITOR] Checking for orphaned tasks (parent job missing)...")
            orphaned_tasks = self.repo.get_orphaned_tasks()
            result.items_scanned += len(orphaned_tasks)

            if orphaned_tasks:
                logger.warning(f"[JANITOR] Found {len(orphaned_tasks)} orphaned tasks!")
                for i, task in enumerate(orphaned_tasks, 1):
                    logger.warning(
                        f"[JANITOR] Orphaned task {i}/{len(orphaned_tasks)}: "
                        f"task_id={task['task_id']}, "
                        f"missing_job_id={task['parent_job_id'][:16]}..., "
                        f"status={task['status']}, "
                        f"task_type={task.get('task_type')}, "
                        f"created_at={task.get('created_at')}"
                    )
                    result.actions_taken.append({
                        "action": "detected_orphaned_task",
                        "task_id": task['task_id'],
                        "parent_job_id": task['parent_job_id'],
                        "status": task['status'],
                        "task_type": task.get('task_type'),
                        "created_at": task.get('created_at', '').isoformat() if task.get('created_at') else None,
                        "reason": "parent_job_missing"
                    })

                # Mark orphaned tasks as failed
                task_ids = [t['task_id'] for t in orphaned_tasks]
                self.repo.mark_tasks_as_failed(
                    task_ids,
                    "[JANITOR] Orphaned task - parent job does not exist"
                )
                result.items_fixed += len(task_ids)
                logger.info(f"[JANITOR] Marked {len(task_ids)} orphaned tasks as FAILED")
            else:
                logger.info("[JANITOR] No orphaned tasks found")

            # 2. Find zombie jobs
            logger.info("[JANITOR] Checking for zombie jobs (PROCESSING but all tasks terminal)...")
            zombie_jobs = self.repo.get_zombie_jobs()
            result.items_scanned += len(zombie_jobs)

            if zombie_jobs:
                logger.warning(f"[JANITOR] Found {len(zombie_jobs)} zombie jobs!")
                for i, job in enumerate(zombie_jobs, 1):
                    job_id = job['job_id']
                    job_type = job.get('job_type')
                    completed = job.get('completed_tasks', 0)
                    failed = job.get('failed_tasks', 0)
                    total = job.get('total_tasks', 0)

                    logger.warning(
                        f"[JANITOR] Zombie job {i}/{len(zombie_jobs)}: "
                        f"job_id={job_id[:16]}..., "
                        f"job_type={job_type}, "
                        f"stage={job.get('stage')}/{job.get('total_stages')}, "
                        f"tasks: {completed} completed, {failed} failed (total={total})"
                    )

                    # Determine if job should be marked completed or failed
                    if failed > 0:
                        # Has failed tasks - mark as failed
                        partial_results = self._build_partial_results(job_id, job)
                        self.repo.mark_job_as_failed(
                            job_id,
                            "[JANITOR] Zombie job detected - tasks finished but job stuck in PROCESSING",
                            partial_results
                        )
                        result.items_fixed += 1
                        result.actions_taken.append({
                            "action": "mark_zombie_job_failed",
                            "job_id": job_id,
                            "job_type": job_type,
                            "completed_tasks": completed,
                            "failed_tasks": failed,
                            "reason": "zombie_with_failures"
                        })
                        logger.info(f"[JANITOR] Marked zombie job FAILED: {job_id[:16]}... (had {failed} failed tasks)")
                    else:
                        # All tasks completed - likely stage advancement failure
                        # Mark as failed with descriptive message
                        self.repo.mark_job_as_failed(
                            job_id,
                            "[JANITOR] Zombie job detected - all tasks completed but job stuck in PROCESSING. "
                            "Likely stage advancement failure.",
                            {"status": "zombie_recovery", "tasks_completed": completed}
                        )
                        result.items_fixed += 1
                        result.actions_taken.append({
                            "action": "mark_zombie_job_failed",
                            "job_id": job_id,
                            "job_type": job_type,
                            "completed_tasks": completed,
                            "reason": "zombie_stage_advancement_failure"
                        })
                        logger.info(f"[JANITOR] Marked zombie job FAILED: {job_id[:16]}... (stage advancement failure)")
            else:
                logger.info("[JANITOR] No zombie jobs found")

            # 3. Find stuck QUEUED jobs
            logger.info(f"[JANITOR] Checking for stuck QUEUED jobs (no tasks after {self.config.queued_timeout_hours}h)...")
            stuck_queued = self.repo.get_stuck_queued_jobs(
                timeout_hours=self.config.queued_timeout_hours
            )
            result.items_scanned += len(stuck_queued)

            if stuck_queued:
                logger.warning(f"[JANITOR] Found {len(stuck_queued)} stuck QUEUED jobs!")
                for i, job in enumerate(stuck_queued, 1):
                    job_id = job['job_id']
                    hours_stuck = job.get('hours_stuck', 0)

                    logger.warning(
                        f"[JANITOR] Stuck QUEUED job {i}/{len(stuck_queued)}: "
                        f"job_id={job_id[:16]}..., "
                        f"job_type={job.get('job_type')}, "
                        f"stuck_for={hours_stuck:.1f}h, "
                        f"created_at={job.get('created_at')}"
                    )

                    self.repo.mark_job_as_failed(
                        job_id,
                        f"[JANITOR] Job stuck in QUEUED state for {hours_stuck:.1f} hours "
                        f"without any tasks created. Job processing likely failed before task creation."
                    )
                    result.items_fixed += 1
                    result.actions_taken.append({
                        "action": "mark_stuck_queued_failed",
                        "job_id": job_id,
                        "job_type": job.get('job_type'),
                        "hours_stuck": round(hours_stuck, 2),
                        "reason": "no_tasks_created"
                    })
                    logger.info(f"[JANITOR] Marked stuck QUEUED job FAILED: {job_id[:16]}... (stuck {hours_stuck:.1f}h)")
            else:
                logger.info("[JANITOR] No stuck QUEUED jobs found")

            # 4. Find ancient stale jobs
            logger.info(f"[JANITOR] Checking for ancient stale jobs (PROCESSING > {self.config.job_stale_hours}h)...")
            ancient_jobs = self.repo.get_ancient_stale_jobs(
                timeout_hours=self.config.job_stale_hours
            )
            result.items_scanned += len(ancient_jobs)

            if ancient_jobs:
                logger.warning(f"[JANITOR] Found {len(ancient_jobs)} ancient stale jobs!")
                for i, job in enumerate(ancient_jobs, 1):
                    job_id = job['job_id']
                    hours_stuck = job.get('hours_stuck', 0)

                    logger.warning(
                        f"[JANITOR] Ancient stale job {i}/{len(ancient_jobs)}: "
                        f"job_id={job_id[:16]}..., "
                        f"job_type={job.get('job_type')}, "
                        f"stage={job.get('stage')}/{job.get('total_stages')}, "
                        f"stuck_for={hours_stuck:.1f}h, "
                        f"task_count={job.get('task_count', 0)}"
                    )

                    partial_results = self._build_partial_results(job_id, job)
                    self.repo.mark_job_as_failed(
                        job_id,
                        f"[JANITOR] Job stuck in PROCESSING for {hours_stuck:.1f} hours. "
                        f"Jobs should complete within {self.config.job_stale_hours} hours.",
                        partial_results
                    )
                    result.items_fixed += 1
                    result.actions_taken.append({
                        "action": "mark_ancient_job_failed",
                        "job_id": job_id,
                        "job_type": job.get('job_type'),
                        "hours_stuck": round(hours_stuck, 2),
                        "task_count": job.get('task_count', 0),
                        "reason": "exceeded_max_duration"
                    })
                    logger.info(f"[JANITOR] Marked ancient stale job FAILED: {job_id[:16]}... (stuck {hours_stuck:.1f}h)")
            else:
                logger.info("[JANITOR] No ancient stale jobs found")

            # Summary
            logger.warning(
                f"[JANITOR] Orphan detection complete: "
                f"scanned={result.items_scanned} records, "
                f"fixed={result.items_fixed} issues"
            )
            logger.debug(
                f"[JANITOR] orphan_detector: Success - "
                f"orphaned_tasks={len(orphaned_tasks) if orphaned_tasks else 0}, "
                f"zombie_jobs={len(zombie_jobs) if zombie_jobs else 0}, "
                f"stuck_queued={len(stuck_queued) if stuck_queued else 0}, "
                f"ancient_jobs={len(ancient_jobs) if ancient_jobs else 0}"
            )
            result.complete(success=True)

        except Exception as e:
            logger.error(f"[JANITOR] Orphan detection failed: {e}")
            import traceback
            logger.error(f"[JANITOR] Traceback: {traceback.format_exc()}")
            result.complete(success=False, error=str(e))

        logger.debug(f"[JANITOR] orphan_detector: Logging run to janitor_runs table")
        self._complete_run(result)
        logger.debug(f"[JANITOR] orphan_detector: Run complete, returning result")
        return result

    # ========================================================================
    # AUDIT LOGGING
    # ========================================================================

    def _start_run(self, result: JanitorRunResult) -> Optional[str]:
        """
        Create audit record at START of janitor run.

        This ensures we have evidence of activity even if the run crashes.

        Returns:
            run_id (UUID string) or None if logging fails
        """
        try:
            run_id = self.repo.log_janitor_run(
                run_type=result.run_type,
                started_at=result.started_at,
                completed_at=None,  # Not completed yet
                items_scanned=0,  # Don't know yet
                items_fixed=0,  # Don't know yet
                actions_taken=[],  # Empty at start
                status="running",  # IN PROGRESS
                error_details=None
            )
            logger.info(f"[JANITOR] Created audit record: run_id={run_id}, type={result.run_type}")
            return run_id
        except Exception as e:
            # Don't fail the janitor if audit logging fails
            logger.error(f"[JANITOR] Failed to create audit record (non-fatal): {e}")
            import traceback
            logger.error(f"[JANITOR] Traceback: {traceback.format_exc()}")
            return None

    def _complete_run(self, result: JanitorRunResult):
        """
        Update audit record at END of janitor run with results.

        If no run_id exists (logging failed at start), tries to create record anyway.
        """
        if not result.run_id:
            logger.warning(f"[JANITOR] No run_id for {result.run_type} - audit record wasn't created at start")
            # Try to create it now anyway
            result.run_id = self._start_run(result)

        try:
            # Update the existing record with final results
            self.repo.update_janitor_run(
                run_id=result.run_id,
                completed_at=result.completed_at or datetime.now(timezone.utc),
                items_scanned=result.items_scanned,
                items_fixed=result.items_fixed,
                actions_taken=result.actions_taken,
                status="completed" if result.success else "failed",
                error_details=result.error
            )
            logger.info(
                f"[JANITOR] Updated audit record: run_id={result.run_id}, "
                f"status={'completed' if result.success else 'failed'}, "
                f"scanned={result.items_scanned}, fixed={result.items_fixed}"
            )
        except Exception as e:
            # Don't fail the janitor if audit logging fails
            logger.error(f"[JANITOR] Failed to update audit record (non-fatal): {e}")
            import traceback
            logger.error(f"[JANITOR] Traceback: {traceback.format_exc()}")

    # ========================================================================
    # STATUS / HISTORY
    # ========================================================================

    def get_status(self) -> Dict[str, Any]:
        """
        Get current janitor status and configuration.

        Returns:
            Dict with configuration and recent run statistics
        """
        recent_runs = self.repo.get_recent_janitor_runs(hours=24, limit=10)

        # Calculate statistics
        total_runs = len(recent_runs)
        failed_runs = sum(1 for r in recent_runs if r.get('status') == 'failed')
        total_fixed = sum(r.get('items_fixed', 0) for r in recent_runs)

        return {
            "enabled": self.config.enabled,
            "config": {
                "task_timeout_minutes": self.config.task_timeout_minutes,
                "job_stale_hours": self.config.job_stale_hours,
                "queued_timeout_hours": self.config.queued_timeout_hours
            },
            "last_24_hours": {
                "total_runs": total_runs,
                "failed_runs": failed_runs,
                "total_items_fixed": total_fixed
            },
            "recent_runs": [
                {
                    "run_type": r.get('run_type'),
                    "status": r.get('status'),
                    "items_fixed": r.get('items_fixed', 0),
                    "started_at": r.get('started_at'),
                    "duration_ms": r.get('duration_ms')
                }
                for r in recent_runs[:5]
            ]
        }


# ============================================================================
# GEO ORPHAN DETECTOR (10 DEC 2025)
# ============================================================================


class GeoOrphanDetector:
    """
    Detect orphaned tables and metadata in geo schema.

    Detects two types of orphans:
    1. Orphaned Tables: Tables in geo schema without metadata records
    2. Orphaned Metadata: Metadata records for non-existent tables

    Does NOT automatically delete - reports findings for manual review.

    Usage:
        detector = GeoOrphanDetector()
        result = detector.run()

        if result['orphaned_tables']:
            print(f"Found {len(result['orphaned_tables'])} orphaned tables")
    """

    def __init__(self):
        """Initialize with lazy repository loading."""
        self._db_repo = None

    @property
    def db_repo(self):
        """Lazy load database repository."""
        if self._db_repo is None:
            from infrastructure.factory import RepositoryFactory
            repos = RepositoryFactory.create_repositories()
            self._db_repo = repos['job_repo']
        return self._db_repo

    def run(self) -> Dict[str, Any]:
        """
        Run orphan detection and return report.

        Returns:
            Dict with orphaned tables, orphaned metadata, and summary:
            {
                "success": bool,
                "timestamp": str,
                "orphaned_tables": [{"table_name": str, "row_count": int, ...}],
                "orphaned_metadata": [{"table_name": str, "etl_job_id": str, ...}],
                "tracked_tables": [str],
                "summary": {
                    "total_geo_tables": int,
                    "total_metadata_records": int,
                    "tracked": int,
                    "orphaned_tables": int,
                    "orphaned_metadata": int,
                    "health_status": "HEALTHY" | "ORPHANS_DETECTED"
                },
                "duration_seconds": float
            }
        """
        start_time = datetime.now(timezone.utc)

        result = {
            "success": False,
            "timestamp": start_time.isoformat(),
            "orphaned_tables": [],      # Tables without metadata
            "orphaned_metadata": [],    # Metadata without tables
            "tracked_tables": [],       # Healthy tables
            "summary": {}
        }

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Step 1: Get all tables in geo schema (excluding table_metadata itself)
                    cur.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'geo'
                        AND table_type = 'BASE TABLE'
                        AND table_name != 'table_metadata'
                        ORDER BY table_name
                    """)
                    geo_tables = set(row['table_name'] for row in cur.fetchall())

                    # Step 2: Check if table_metadata exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_metadata'
                        )
                    """)
                    metadata_table_exists = cur.fetchone()['exists']

                    if not metadata_table_exists:
                        # No metadata table - all geo tables are orphaned
                        logger.warning("⚠️ GeoOrphanDetector: geo.table_metadata does not exist!")
                        for table_name in sorted(geo_tables):
                            try:
                                cur.execute(f'SELECT COUNT(*) FROM geo."{table_name}"')
                                row_count = cur.fetchone()['count']
                            except Exception:
                                row_count = None

                            result["orphaned_tables"].append({
                                "table_name": table_name,
                                "row_count": row_count,
                                "reason": "Table exists but geo.table_metadata does not exist"
                            })

                        result["summary"] = {
                            "total_geo_tables": len(geo_tables),
                            "total_metadata_records": 0,
                            "tracked": 0,
                            "orphaned_tables": len(geo_tables),
                            "orphaned_metadata": 0,
                            "health_status": "ORPHANS_DETECTED" if geo_tables else "HEALTHY",
                            "metadata_table_missing": True
                        }
                        result["success"] = True
                        result["duration_seconds"] = round(
                            (datetime.now(timezone.utc) - start_time).total_seconds(), 2
                        )
                        return result

                    # Step 3: Get all table names in metadata
                    cur.execute("""
                        SELECT table_name, etl_job_id, created_at
                        FROM geo.table_metadata
                        ORDER BY table_name
                    """)
                    metadata_tables = {}
                    for row in cur.fetchall():
                        metadata_tables[row['table_name']] = {
                            'etl_job_id': row.get('etl_job_id'),
                            'created_at': row['created_at'].isoformat() if row.get('created_at') else None
                        }

                    metadata_names = set(metadata_tables.keys())

                    # Step 4: Identify orphans
                    # Tables without metadata
                    orphaned_tables = geo_tables - metadata_names
                    for table_name in sorted(orphaned_tables):
                        # Get row count for context
                        try:
                            cur.execute(f'SELECT COUNT(*) FROM geo."{table_name}"')
                            row_count = cur.fetchone()['count']
                        except Exception:
                            row_count = None

                        result["orphaned_tables"].append({
                            "table_name": table_name,
                            "row_count": row_count,
                            "reason": "Table exists in geo schema but has no metadata record"
                        })

                    # Metadata without tables
                    orphaned_metadata = metadata_names - geo_tables
                    for table_name in sorted(orphaned_metadata):
                        meta = metadata_tables[table_name]
                        result["orphaned_metadata"].append({
                            "table_name": table_name,
                            "etl_job_id": meta['etl_job_id'],
                            "created_at": meta['created_at'],
                            "reason": "Metadata exists but table was dropped"
                        })

                    # Tracked (healthy) tables
                    tracked = geo_tables & metadata_names
                    result["tracked_tables"] = sorted(tracked)

            # Build summary
            result["summary"] = {
                "total_geo_tables": len(geo_tables),
                "total_metadata_records": len(metadata_tables),
                "tracked": len(result["tracked_tables"]),
                "orphaned_tables": len(result["orphaned_tables"]),
                "orphaned_metadata": len(result["orphaned_metadata"]),
                "health_status": "HEALTHY" if not result["orphaned_tables"] and not result["orphaned_metadata"] else "ORPHANS_DETECTED"
            }

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            result["duration_seconds"] = round(duration, 2)
            result["success"] = True

            # Log findings
            if result["orphaned_tables"]:
                logger.warning(
                    f"⚠️ GeoOrphanDetector: Found {len(result['orphaned_tables'])} orphaned tables: "
                    f"{[t['table_name'] for t in result['orphaned_tables']]}"
                )
            if result["orphaned_metadata"]:
                logger.warning(
                    f"⚠️ GeoOrphanDetector: Found {len(result['orphaned_metadata'])} orphaned metadata records: "
                    f"{[m['table_name'] for m in result['orphaned_metadata']]}"
                )
            if not result["orphaned_tables"] and not result["orphaned_metadata"]:
                logger.info(
                    f"✅ GeoOrphanDetector: All {len(result['tracked_tables'])} geo tables are tracked"
                )

            return result

        except Exception as e:
            logger.error(f"❌ GeoOrphanDetector failed: {e}")
            result["error"] = str(e)
            result["duration_seconds"] = round(
                (datetime.now(timezone.utc) - start_time).total_seconds(), 2
            )
            return result


# Singleton instance for easy import
geo_orphan_detector = GeoOrphanDetector()


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = ['JanitorService', 'JanitorConfig', 'JanitorRunResult', 'GeoOrphanDetector', 'geo_orphan_detector']
