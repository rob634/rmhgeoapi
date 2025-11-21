# ============================================================================
# CLAUDE CONTEXT - JANITOR SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - Janitor maintenance business logic
# PURPOSE: Business logic for janitor maintenance operations
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: JanitorService
# INTERFACES: Uses JanitorRepository for database access
# PYDANTIC_MODELS: JanitorRunResult (dataclass)
# DEPENDENCIES: infrastructure.janitor_repository, util_logger, datetime
# SOURCE: Timer triggers call this service
# SCOPE: Maintenance operations for detecting and fixing stale/failed records
# VALIDATION: Business rule validation
# PATTERNS: Service pattern, Strategy pattern (different detection strategies)
# ENTRY_POINTS: from services.janitor_service import JanitorService
# ============================================================================

"""
Janitor Service - Maintenance Business Logic

Coordinates janitor operations between timer triggers and the repository:

1. Task Watchdog: Detect and fix stale PROCESSING tasks
2. Job Health Monitor: Detect jobs with failed tasks, capture partial results
3. Orphan Detector: Find and handle orphaned tasks and zombie jobs

This service does NOT use CoreMachine - it runs via standalone timer triggers.
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

        if not self.config.enabled:
            logger.info("Janitor disabled via configuration - skipping task watchdog")
            result.complete(success=True)
            return result

        try:
            logger.info(
                f"Starting task watchdog (timeout: {self.config.task_timeout_minutes} min)"
            )

            # Find stale tasks
            stale_tasks = self.repo.get_stale_processing_tasks(
                timeout_minutes=self.config.task_timeout_minutes
            )
            result.items_scanned = len(stale_tasks)

            if not stale_tasks:
                logger.info("No stale tasks found")
                result.complete(success=True)
                self._log_run(result)
                return result

            logger.warning(f"Found {len(stale_tasks)} stale PROCESSING tasks")

            # Mark tasks as failed
            task_ids = [t['task_id'] for t in stale_tasks]
            error_message = (
                f"[JANITOR] Silent failure detected - task exceeded "
                f"{self.config.task_timeout_minutes} minute timeout. "
                f"Azure Functions max execution time is 10-30 minutes."
            )

            fixed_count = self.repo.mark_tasks_as_failed(task_ids, error_message)
            result.items_fixed = fixed_count

            # Record actions
            for task in stale_tasks:
                result.actions_taken.append({
                    "action": "mark_task_failed",
                    "task_id": task['task_id'],
                    "parent_job_id": task['parent_job_id'],
                    "minutes_stuck": round(task.get('minutes_stuck', 0), 1),
                    "reason": "exceeded_timeout"
                })

            logger.info(f"Marked {fixed_count} stale tasks as FAILED")
            result.complete(success=True)

        except Exception as e:
            logger.error(f"Task watchdog failed: {e}")
            result.complete(success=False, error=str(e))

        self._log_run(result)
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

        if not self.config.enabled:
            logger.info("Janitor disabled via configuration - skipping job health check")
            result.complete(success=True)
            return result

        try:
            logger.info("Starting job health check")

            # Find jobs with failed tasks
            failed_jobs = self.repo.get_processing_jobs_with_failed_tasks()
            result.items_scanned = len(failed_jobs)

            if not failed_jobs:
                logger.info("No jobs with failed tasks found")
                result.complete(success=True)
                self._log_run(result)
                return result

            logger.warning(f"Found {len(failed_jobs)} PROCESSING jobs with failed tasks")

            # Process each failed job
            for job in failed_jobs:
                job_id = job['job_id']
                failed_count = job.get('failed_count', 0)
                completed_count = job.get('completed_count', 0)
                total_tasks = job.get('total_tasks', 0)
                failed_task_ids = job.get('failed_task_ids', [])
                failed_errors = job.get('failed_task_errors', [])

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
                        "job_type": job.get('job_type'),
                        "failed_tasks": failed_count,
                        "completed_tasks": completed_count,
                        "total_tasks": total_tasks,
                        "reason": "task_failures"
                    })

            logger.info(f"Marked {result.items_fixed} jobs as FAILED")
            result.complete(success=True)

        except Exception as e:
            logger.error(f"Job health check failed: {e}")
            result.complete(success=False, error=str(e))

        self._log_run(result)
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

        if not self.config.enabled:
            logger.info("Janitor disabled via configuration - skipping orphan detection")
            result.complete(success=True)
            return result

        try:
            logger.info("Starting orphan detection")

            # 1. Find orphaned tasks
            orphaned_tasks = self.repo.get_orphaned_tasks()
            result.items_scanned += len(orphaned_tasks)

            if orphaned_tasks:
                logger.warning(f"Found {len(orphaned_tasks)} orphaned tasks")
                for task in orphaned_tasks:
                    result.actions_taken.append({
                        "action": "detected_orphaned_task",
                        "task_id": task['task_id'],
                        "parent_job_id": task['parent_job_id'],
                        "status": task['status'],
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

            # 2. Find zombie jobs
            zombie_jobs = self.repo.get_zombie_jobs()
            result.items_scanned += len(zombie_jobs)

            if zombie_jobs:
                logger.warning(f"Found {len(zombie_jobs)} zombie jobs")
                for job in zombie_jobs:
                    # Determine if job should be marked completed or failed
                    if job.get('failed_tasks', 0) > 0:
                        # Has failed tasks - mark as failed
                        partial_results = self._build_partial_results(job['job_id'], job)
                        self.repo.mark_job_as_failed(
                            job['job_id'],
                            "[JANITOR] Zombie job detected - tasks finished but job stuck in PROCESSING",
                            partial_results
                        )
                        result.items_fixed += 1
                        result.actions_taken.append({
                            "action": "mark_zombie_job_failed",
                            "job_id": job['job_id'],
                            "reason": "zombie_with_failures"
                        })
                    else:
                        # All tasks completed - likely stage advancement failure
                        # Mark as failed with descriptive message
                        self.repo.mark_job_as_failed(
                            job['job_id'],
                            "[JANITOR] Zombie job detected - all tasks completed but job stuck in PROCESSING. "
                            "Likely stage advancement failure.",
                            {"status": "zombie_recovery", "tasks_completed": job.get('completed_tasks', 0)}
                        )
                        result.items_fixed += 1
                        result.actions_taken.append({
                            "action": "mark_zombie_job_failed",
                            "job_id": job['job_id'],
                            "reason": "zombie_stage_advancement_failure"
                        })

            # 3. Find stuck QUEUED jobs
            stuck_queued = self.repo.get_stuck_queued_jobs(
                timeout_hours=self.config.queued_timeout_hours
            )
            result.items_scanned += len(stuck_queued)

            if stuck_queued:
                logger.warning(f"Found {len(stuck_queued)} stuck QUEUED jobs")
                for job in stuck_queued:
                    self.repo.mark_job_as_failed(
                        job['job_id'],
                        f"[JANITOR] Job stuck in QUEUED state for {job.get('hours_stuck', '?'):.1f} hours "
                        f"without any tasks created. Job processing likely failed before task creation."
                    )
                    result.items_fixed += 1
                    result.actions_taken.append({
                        "action": "mark_stuck_queued_failed",
                        "job_id": job['job_id'],
                        "hours_stuck": round(job.get('hours_stuck', 0), 2),
                        "reason": "no_tasks_created"
                    })

            # 4. Find ancient stale jobs
            ancient_jobs = self.repo.get_ancient_stale_jobs(
                timeout_hours=self.config.job_stale_hours
            )
            result.items_scanned += len(ancient_jobs)

            if ancient_jobs:
                logger.warning(f"Found {len(ancient_jobs)} ancient stale jobs")
                for job in ancient_jobs:
                    partial_results = self._build_partial_results(job['job_id'], job)
                    self.repo.mark_job_as_failed(
                        job['job_id'],
                        f"[JANITOR] Job stuck in PROCESSING for {job.get('hours_stuck', '?'):.1f} hours. "
                        f"Jobs should complete within {self.config.job_stale_hours} hours.",
                        partial_results
                    )
                    result.items_fixed += 1
                    result.actions_taken.append({
                        "action": "mark_ancient_job_failed",
                        "job_id": job['job_id'],
                        "hours_stuck": round(job.get('hours_stuck', 0), 2),
                        "task_count": job.get('task_count', 0),
                        "reason": "exceeded_max_duration"
                    })

            logger.info(
                f"Orphan detection complete: scanned={result.items_scanned}, "
                f"fixed={result.items_fixed}"
            )
            result.complete(success=True)

        except Exception as e:
            logger.error(f"Orphan detection failed: {e}")
            result.complete(success=False, error=str(e))

        self._log_run(result)
        return result

    # ========================================================================
    # AUDIT LOGGING
    # ========================================================================

    def _log_run(self, result: JanitorRunResult):
        """Log a janitor run to the audit table."""
        try:
            run_id = self.repo.log_janitor_run(
                run_type=result.run_type,
                started_at=result.started_at,
                completed_at=result.completed_at or datetime.now(timezone.utc),
                items_scanned=result.items_scanned,
                items_fixed=result.items_fixed,
                actions_taken=result.actions_taken,
                status="completed" if result.success else "failed",
                error_details=result.error
            )
            result.run_id = run_id
        except Exception as e:
            # Don't fail the janitor if audit logging fails
            logger.warning(f"Failed to log janitor run (non-fatal): {e}")

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
# MODULE EXPORTS
# ============================================================================

__all__ = ['JanitorService', 'JanitorConfig', 'JanitorRunResult']
