# ============================================================================
# JANITOR SERVICE
# ============================================================================
# STATUS: Services - Maintenance operations coordinator
# PURPOSE: Task watchdog, job health monitor, orphan detector (timer-triggered)
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
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
from infrastructure.service_bus import ServiceBusRepository
from core.schema.queue import TaskQueueMessage
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

    Function App vs Docker Task Timeouts (22 JAN 2026):
        Function App tasks have hard 10-30 minute timeout limits.
        Docker tasks can run for hours (COG processing, H3 pyramids, etc).
        Separate timeout configurations prevent Janitor from interfering
        with legitimate long-running Docker tasks.
    """

    # Task watchdog settings - Function App tasks
    task_timeout_minutes: int = 30  # Azure Functions max is 10-30 min

    # Task watchdog settings - Docker worker tasks (22 JAN 2026)
    # Docker tasks can legitimately run for hours (large COGs, H3 pyramids)
    # Use much longer timeout to avoid interfering with valid processing
    docker_task_timeout_hours: int = 24  # Docker tasks can run up to 24 hours

    # Orphaned pending task settings (16 DEC 2025 - PENDING status tracking)
    # PENDING = task created, message sent but trigger hasn't confirmed receipt yet
    orphaned_pending_timeout_minutes: int = 2  # Message should reach trigger within seconds

    # Orphaned queued task settings (14 DEC 2025 - message loss recovery)
    orphaned_queued_timeout_minutes: int = 5  # Tasks stuck in QUEUED > this are orphaned
    orphaned_queued_max_retries: int = 3  # Max re-queue attempts before marking failed

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
            docker_task_timeout_hours=int(os.environ.get("JANITOR_DOCKER_TASK_TIMEOUT_HOURS", "24")),
            orphaned_pending_timeout_minutes=int(os.environ.get("JANITOR_ORPHANED_PENDING_TIMEOUT_MINUTES", "2")),
            orphaned_queued_timeout_minutes=int(os.environ.get("JANITOR_ORPHANED_QUEUED_TIMEOUT_MINUTES", "5")),
            orphaned_queued_max_retries=int(os.environ.get("JANITOR_ORPHANED_QUEUED_MAX_RETRIES", "3")),
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
    # HELPER METHODS FOR ORPHANED TASK RECOVERY (14 DEC 2025)
    # ========================================================================

    def _get_queue_for_task(self, task_type: str) -> str:
        """
        Determine the correct Service Bus queue for a task type.

        Uses the same routing logic as CoreMachine.

        Args:
            task_type: Type of task (e.g., 'validate_raster', 'create_cog')

        Returns:
            Queue name ('container-tasks', 'functionapp-tasks', or 'geospatial-jobs')
        """
        from config.defaults import TaskRoutingDefaults, QueueDefaults

        # V0.8: Consolidated queue routing
        if task_type in TaskRoutingDefaults.DOCKER_TASKS:
            return QueueDefaults.CONTAINER_TASKS_QUEUE
        elif task_type in TaskRoutingDefaults.FUNCTIONAPP_TASKS:
            return QueueDefaults.FUNCTIONAPP_TASKS_QUEUE
        else:
            # Default to jobs queue for unknown types
            return QueueDefaults.JOBS_QUEUE

    def _increment_task_retry_count(self, task_id: str) -> bool:
        """
        Increment retry count for a task in the database.

        Args:
            task_id: Task ID to update

        Returns:
            True if successful, False otherwise
        """
        from psycopg import sql

        query = sql.SQL("""
            UPDATE {schema}.tasks
            SET retry_count = retry_count + 1,
                updated_at = NOW()
            WHERE task_id = %s
            RETURNING task_id, retry_count
        """).format(schema=sql.Identifier("app"))

        try:
            with self.repo._error_context("increment task retry count"):
                result = self.repo._execute_query(query, (task_id,), fetch='one')
                if result:
                    logger.debug(
                        f"[JANITOR] Incremented retry_count for task {task_id[:16]}... "
                        f"to {result['retry_count']}"
                    )
                    return True
                return False
        except Exception as e:
            logger.error(f"[JANITOR] Failed to increment retry count for {task_id[:16]}...: {e}")
            return False

    def _reset_task_to_pending(self, task_id: str) -> bool:
        """
        Reset a PROCESSING task back to PENDING status for re-queue.

        16 DEC 2025: Changed from QUEUED to PENDING for honest message tracking.
        Task goes to PENDING, message is re-sent, trigger confirms PENDING→QUEUED.

        Used for PROCESSING tasks that timed out without ever starting
        (last_pulse is None), allowing them to be retried.

        Args:
            task_id: Task ID to reset

        Returns:
            True if successful, False otherwise
        """
        from psycopg import sql

        query = sql.SQL("""
            UPDATE {schema}.tasks
            SET status = 'pending',
                updated_at = NOW()
            WHERE task_id = %s
            AND status = 'processing'
            RETURNING task_id, status
        """).format(schema=sql.Identifier("app"))

        try:
            with self.repo._error_context("reset task to PENDING"):
                result = self.repo._execute_query(query, (task_id,), fetch='one')
                if result:
                    logger.debug(
                        f"[JANITOR] Reset task {task_id[:16]}... from PROCESSING to PENDING"
                    )
                    return True
                return False
        except Exception as e:
            logger.error(f"[JANITOR] Failed to reset task {task_id[:16]}... to PENDING: {e}")
            return False

    # ========================================================================
    # TASK WATCHDOG
    # ========================================================================

    def run_task_watchdog(self) -> JanitorRunResult:
        """
        Detect and fix stale PROCESSING tasks + recover orphaned QUEUED tasks.

        Two independent checks:
        1. Tasks stuck in PROCESSING > 30 min → mark FAILED (function timed out)
        2. Tasks stuck in QUEUED > 5 min → peek queue, re-queue if message lost

        Returns:
            JanitorRunResult with statistics and actions taken
        """
        result = JanitorRunResult(run_type="task_watchdog", success=False)
        logger.info(
            f"[JANITOR] ========== TASK WATCHDOG STARTING =========="
        )

        # Create audit record FIRST before doing any work
        result.run_id = self._start_run(result)

        if not self.config.enabled:
            logger.info("[JANITOR] Janitor disabled via configuration - skipping")
            result.complete(success=True)
            self._complete_run(result)
            return result

        try:
            # ================================================================
            # PART 1: STALE FUNCTION APP TASKS (tasks that timed out)
            # 15 DEC 2025: Added retry logic for tasks that never started
            # 22 JAN 2026: Excludes Docker/long-running tasks (separate handling)
            # ================================================================
            from config.defaults import TaskRoutingDefaults

            logger.info(
                f"[JANITOR] PART 1: Checking for stale Function App PROCESSING tasks "
                f"(>{self.config.task_timeout_minutes}min, excluding Docker tasks)"
            )

            stale_tasks = self.repo.get_stale_processing_tasks(
                timeout_minutes=self.config.task_timeout_minutes,
                exclude_task_types=TaskRoutingDefaults.DOCKER_TASKS
            )
            result.items_scanned += len(stale_tasks)

            if stale_tasks:
                logger.warning(f"[JANITOR] Found {len(stale_tasks)} stale PROCESSING tasks")

                # Get Service Bus for re-queuing
                service_bus = ServiceBusRepository()

                requeued_count = 0
                failed_count = 0

                for i, task in enumerate(stale_tasks, 1):
                    task_id = task['task_id']
                    retry_count = task.get('retry_count', 0)
                    last_pulse = task.get('last_pulse')
                    minutes_stuck = round(task.get('minutes_stuck', 0), 1)
                    task_type = task.get('task_type', '')

                    logger.warning(
                        f"[JANITOR] Stale PROCESSING {i}/{len(stale_tasks)}: "
                        f"task_id={task_id}, "
                        f"job_id={task['parent_job_id'][:16]}..., "
                        f"task_type={task_type}, "
                        f"stuck={minutes_stuck}min, "
                        f"last_pulse={'SET' if last_pulse else 'None'}, "
                        f"retry_count={retry_count}"
                    )

                    # RETRY LOGIC (15 DEC 2025):
                    # - If last_pulse is None: task was never started (platform issue)
                    # - If retry_count < max: we can retry
                    # - If last_pulse is SET: task actually ran and failed (code error)
                    can_retry = (
                        last_pulse is None and
                        retry_count < self.config.orphaned_queued_max_retries
                    )

                    if can_retry:
                        # Task never started - re-queue for retry
                        try:
                            queue_name = self._get_queue_for_task(task_type)

                            # Build TaskQueueMessage
                            message = TaskQueueMessage(
                                task_id=task_id,
                                parent_job_id=task['parent_job_id'],
                                job_type=task.get('job_type', ''),
                                task_type=task_type,
                                stage=task.get('stage', 1),
                                task_index=task.get('task_index', 0),
                                parameters=task.get('parameters', {})
                            )

                            # Reset status to PENDING first (16 DEC 2025)
                            if not self._reset_task_to_pending(task_id):
                                logger.error(f"[JANITOR] Failed to reset task {task_id[:16]}... to PENDING")
                                continue

                            # Send to queue
                            message_id = service_bus.send_message(queue_name, message)

                            # Increment retry count
                            self._increment_task_retry_count(task_id)

                            requeued_count += 1
                            result.items_fixed += 1
                            result.actions_taken.append({
                                "action": "requeue_stale_processing_task",
                                "task_id": task_id,
                                "parent_job_id": task['parent_job_id'],
                                "task_type": task_type,
                                "queue": queue_name,
                                "retry_count": retry_count + 1,
                                "max_retries": self.config.orphaned_queued_max_retries,
                                "minutes_stuck": minutes_stuck,
                                "message_id": message_id,
                                "reason": "processing_timeout_no_pulse"
                            })

                            logger.info(
                                f"[JANITOR] ✅ Re-queued stale PROCESSING task: task_id={task_id[:16]}..., "
                                f"queue={queue_name}, retry={retry_count + 1}/{self.config.orphaned_queued_max_retries}, "
                                f"message_id={message_id}"
                            )

                        except Exception as requeue_error:
                            logger.error(
                                f"[JANITOR] ❌ Failed to re-queue stale task {task_id[:16]}...: {requeue_error}"
                            )
                            result.actions_taken.append({
                                "action": "requeue_failed",
                                "task_id": task_id,
                                "error": str(requeue_error)
                            })
                    else:
                        # Cannot retry - mark as FAILED
                        if last_pulse:
                            reason = "task_executed_but_timed_out"
                            error_message = (
                                f"[JANITOR] Task exceeded {self.config.task_timeout_minutes} minute timeout. "
                                f"Task started executing (last_pulse set) but did not complete."
                            )
                        else:
                            reason = "max_retries_exceeded"
                            error_message = (
                                f"[JANITOR] Task exceeded {self.config.task_timeout_minutes} minute timeout. "
                                f"Max retries ({self.config.orphaned_queued_max_retries}) exhausted - "
                                f"task failed {retry_count + 1} times without ever starting."
                            )

                        self.repo.mark_tasks_as_failed([task_id], error_message)
                        failed_count += 1
                        result.items_fixed += 1
                        result.actions_taken.append({
                            "action": "mark_processing_task_failed",
                            "task_id": task_id,
                            "parent_job_id": task['parent_job_id'],
                            "task_type": task_type,
                            "minutes_stuck": minutes_stuck,
                            "retry_count": retry_count,
                            "last_pulse_set": last_pulse is not None,
                            "reason": reason
                        })

                        logger.warning(
                            f"[JANITOR] ❌ Marked stale PROCESSING task FAILED: task_id={task_id[:16]}..., "
                            f"reason={reason}, retries={retry_count}"
                        )

                logger.info(
                    f"[JANITOR] Stale PROCESSING task handling complete: "
                    f"re-queued={requeued_count}, failed={failed_count}"
                )
            else:
                logger.info("[JANITOR] No stale Function App PROCESSING tasks found ✓")

            # ================================================================
            # PART 1B: STALE DOCKER TASKS (22 JAN 2026)
            # Docker tasks have much longer timeout (hours, not minutes)
            # Only mark as failed - no retry logic for these long-running tasks
            # ================================================================
            logger.info(
                f"[JANITOR] PART 1B: Checking for stale Docker PROCESSING tasks "
                f"(>{self.config.docker_task_timeout_hours}h)"
            )

            stale_docker_tasks = self.repo.get_stale_docker_tasks(
                timeout_hours=self.config.docker_task_timeout_hours,
                docker_task_types=TaskRoutingDefaults.DOCKER_TASKS
            )
            result.items_scanned += len(stale_docker_tasks)

            if stale_docker_tasks:
                logger.warning(
                    f"[JANITOR] Found {len(stale_docker_tasks)} stale Docker PROCESSING tasks "
                    f"(>{self.config.docker_task_timeout_hours}h)"
                )

                docker_failed_count = 0

                for i, task in enumerate(stale_docker_tasks, 1):
                    task_id = task['task_id']
                    hours_stuck = round(task.get('hours_stuck', 0), 1)
                    task_type = task.get('task_type', '')
                    last_pulse = task.get('last_pulse')

                    logger.warning(
                        f"[JANITOR] Stale Docker task {i}/{len(stale_docker_tasks)}: "
                        f"task_id={task_id[:16]}..., "
                        f"job_id={task['parent_job_id'][:16]}..., "
                        f"task_type={task_type}, "
                        f"stuck={hours_stuck}h, "
                        f"last_pulse={'SET' if last_pulse else 'None'}"
                    )

                    # Docker tasks that exceed 24 hours are considered failed
                    # No retry logic - if it ran that long and didn't finish, something is wrong
                    error_message = (
                        f"[JANITOR] Docker task exceeded {self.config.docker_task_timeout_hours} hour timeout. "
                        f"Task ran for {hours_stuck}h without completing. "
                        f"last_pulse={'set' if last_pulse else 'never set'}."
                    )

                    self.repo.mark_tasks_as_failed([task_id], error_message)
                    docker_failed_count += 1
                    result.items_fixed += 1
                    result.actions_taken.append({
                        "action": "mark_docker_task_failed",
                        "task_id": task_id,
                        "parent_job_id": task['parent_job_id'],
                        "task_type": task_type,
                        "hours_stuck": hours_stuck,
                        "last_pulse_set": last_pulse is not None,
                        "reason": "docker_task_timeout"
                    })

                    logger.warning(
                        f"[JANITOR] ❌ Marked stale Docker task FAILED: task_id={task_id[:16]}..., "
                        f"hours_stuck={hours_stuck}h"
                    )

                logger.info(
                    f"[JANITOR] Stale Docker task handling complete: failed={docker_failed_count}"
                )
            else:
                logger.info("[JANITOR] No stale Docker PROCESSING tasks found ✓")

            # ================================================================
            # PART 2: ORPHANED QUEUED TASKS (messages lost in Service Bus)
            # ================================================================
            logger.info(
                f"[JANITOR] PART 2: Checking for orphaned QUEUED tasks "
                f"(>{self.config.orphaned_queued_timeout_minutes}min)"
            )

            orphaned_tasks = self.repo.get_orphaned_queued_tasks(
                timeout_minutes=self.config.orphaned_queued_timeout_minutes,
                limit=50
            )
            result.items_scanned += len(orphaned_tasks)

            if orphaned_tasks:
                logger.warning(
                    f"[JANITOR] Found {len(orphaned_tasks)} potentially orphaned QUEUED tasks - "
                    f"verifying queue messages..."
                )

                # Get Service Bus repository for peek and re-queue
                service_bus = ServiceBusRepository()

                requeued_count = 0
                skipped_count = 0
                failed_count = 0

                for task in orphaned_tasks:
                    task_id = task['task_id']
                    retry_count = task.get('retry_count', 0)
                    minutes_stuck = round(task.get('minutes_stuck', 0), 1)
                    task_type = task.get('task_type', '')
                    queue_name = self._get_queue_for_task(task_type)

                    logger.info(
                        f"[JANITOR] Checking orphaned task: task_id={task_id}, "
                        f"job_id={task['parent_job_id'][:16]}..., "
                        f"task_type={task_type}, queue={queue_name}, "
                        f"retry_count={retry_count}, stuck={minutes_stuck}min"
                    )

                    # PEEK QUEUE to verify message is actually missing
                    message_exists = service_bus.message_exists_for_task(queue_name, task_id)

                    if message_exists:
                        # Message found - not orphaned, just slow
                        logger.info(
                            f"[JANITOR] ⏳ Task {task_id[:16]}... has message in queue - "
                            f"skipping (workers may be busy)"
                        )
                        skipped_count += 1
                        result.actions_taken.append({
                            "action": "skip_queued_task",
                            "task_id": task_id,
                            "queue": queue_name,
                            "reason": "message_exists_in_queue",
                            "minutes_stuck": minutes_stuck
                        })
                        continue

                    # Message NOT found - truly orphaned
                    logger.warning(
                        f"[JANITOR] 🚨 Message LOST for task {task_id[:16]}... - "
                        f"not found in queue '{queue_name}'"
                    )

                    if retry_count < self.config.orphaned_queued_max_retries:
                        # Under retry limit - re-queue the task
                        try:
                            # Build TaskQueueMessage
                            message = TaskQueueMessage(
                                task_id=task_id,
                                parent_job_id=task['parent_job_id'],
                                job_type=task.get('job_type', ''),
                                task_type=task_type,
                                stage=task.get('stage', 1),
                                task_index=task.get('task_index', 0),
                                parameters=task.get('parameters', {})
                            )

                            # Send to queue
                            message_id = service_bus.send_message(queue_name, message)

                            # Increment retry count in database
                            self._increment_task_retry_count(task_id)

                            requeued_count += 1
                            result.items_fixed += 1
                            result.actions_taken.append({
                                "action": "requeue_orphaned_task",
                                "task_id": task_id,
                                "parent_job_id": task['parent_job_id'],
                                "task_type": task_type,
                                "queue": queue_name,
                                "retry_count": retry_count + 1,
                                "minutes_stuck": minutes_stuck,
                                "message_id": message_id
                            })

                            logger.info(
                                f"[JANITOR] ✅ Re-queued orphaned task: task_id={task_id}, "
                                f"queue={queue_name}, retry={retry_count + 1}/{self.config.orphaned_queued_max_retries}, "
                                f"message_id={message_id}"
                            )

                        except Exception as requeue_error:
                            logger.error(
                                f"[JANITOR] ❌ Failed to re-queue task {task_id}: {requeue_error}"
                            )
                            result.actions_taken.append({
                                "action": "requeue_failed",
                                "task_id": task_id,
                                "error": str(requeue_error)
                            })
                    else:
                        # Max retries exceeded - mark as failed
                        error_msg = (
                            f"[JANITOR] Orphaned task exceeded max re-queue attempts "
                            f"({self.config.orphaned_queued_max_retries}). "
                            f"Message lost {retry_count + 1} times - giving up."
                        )

                        self.repo.mark_tasks_as_failed([task_id], error_msg)
                        failed_count += 1
                        result.items_fixed += 1
                        result.actions_taken.append({
                            "action": "mark_orphaned_task_failed",
                            "task_id": task_id,
                            "parent_job_id": task['parent_job_id'],
                            "task_type": task_type,
                            "retry_count": retry_count,
                            "reason": "max_retries_exceeded"
                        })

                        logger.warning(
                            f"[JANITOR] ❌ Marked orphaned task FAILED (max retries): "
                            f"task_id={task_id}, retries={retry_count}"
                        )

                logger.info(
                    f"[JANITOR] Orphaned QUEUED task recovery complete: "
                    f"re-queued={requeued_count}, skipped={skipped_count}, failed={failed_count}"
                )
            else:
                logger.info("[JANITOR] No orphaned QUEUED tasks found ✓")

            # ================================================================
            # PART 3: ORPHANED PENDING TASKS (16 DEC 2025 - PENDING status)
            # Tasks stuck in PENDING = message never reached trigger
            # ================================================================
            logger.info(
                f"[JANITOR] PART 3: Checking for orphaned PENDING tasks "
                f"(>{self.config.orphaned_pending_timeout_minutes}min)"
            )

            orphaned_pending = self.repo.get_orphaned_pending_tasks(
                timeout_minutes=self.config.orphaned_pending_timeout_minutes,
                limit=50
            )
            result.items_scanned += len(orphaned_pending)

            if orphaned_pending:
                logger.warning(
                    f"[JANITOR] Found {len(orphaned_pending)} orphaned PENDING tasks - "
                    f"message likely never reached trigger"
                )

                # Get Service Bus for re-queuing
                service_bus = ServiceBusRepository()

                pending_requeued = 0
                pending_failed = 0

                for task in orphaned_pending:
                    task_id = task['task_id']
                    retry_count = task.get('retry_count', 0)
                    minutes_stuck = round(task.get('minutes_stuck', 0), 1)
                    task_type = task.get('task_type', '')
                    queue_name = self._get_queue_for_task(task_type)

                    logger.warning(
                        f"[JANITOR] Orphaned PENDING task: task_id={task_id[:16]}..., "
                        f"job_id={task['parent_job_id'][:16]}..., "
                        f"task_type={task_type}, queue={queue_name}, "
                        f"retry_count={retry_count}, stuck={minutes_stuck}min"
                    )

                    if retry_count < self.config.orphaned_queued_max_retries:
                        # Under retry limit - re-send the message
                        try:
                            # Build TaskQueueMessage
                            message = TaskQueueMessage(
                                task_id=task_id,
                                parent_job_id=task['parent_job_id'],
                                job_type=task.get('job_type', ''),
                                task_type=task_type,
                                stage=task.get('stage', 1),
                                task_index=task.get('task_index', 0),
                                parameters=task.get('parameters', {})
                            )

                            # Send to queue (task stays in PENDING - trigger will update to QUEUED)
                            message_id = service_bus.send_message(queue_name, message)

                            # Increment retry count in database
                            self._increment_task_retry_count(task_id)

                            pending_requeued += 1
                            result.items_fixed += 1
                            result.actions_taken.append({
                                "action": "resend_pending_task",
                                "task_id": task_id,
                                "parent_job_id": task['parent_job_id'],
                                "task_type": task_type,
                                "queue": queue_name,
                                "retry_count": retry_count + 1,
                                "minutes_stuck": minutes_stuck,
                                "message_id": message_id,
                                "reason": "message_never_reached_trigger"
                            })

                            logger.info(
                                f"[JANITOR] ✅ Re-sent PENDING task message: task_id={task_id[:16]}..., "
                                f"queue={queue_name}, retry={retry_count + 1}/{self.config.orphaned_queued_max_retries}, "
                                f"message_id={message_id}"
                            )

                        except Exception as resend_error:
                            logger.error(
                                f"[JANITOR] ❌ Failed to re-send PENDING task {task_id[:16]}...: {resend_error}"
                            )
                            result.actions_taken.append({
                                "action": "resend_pending_failed",
                                "task_id": task_id,
                                "error": str(resend_error)
                            })
                    else:
                        # Max retries exceeded - mark as failed
                        error_msg = (
                            f"[JANITOR] PENDING task message never reached trigger. "
                            f"Max retries ({self.config.orphaned_queued_max_retries}) exhausted - "
                            f"message lost {retry_count + 1} times."
                        )

                        self.repo.mark_tasks_as_failed([task_id], error_msg)
                        pending_failed += 1
                        result.items_fixed += 1
                        result.actions_taken.append({
                            "action": "mark_pending_task_failed",
                            "task_id": task_id,
                            "parent_job_id": task['parent_job_id'],
                            "task_type": task_type,
                            "retry_count": retry_count,
                            "reason": "max_retries_exceeded_pending"
                        })

                        logger.warning(
                            f"[JANITOR] ❌ Marked PENDING task FAILED (max retries): "
                            f"task_id={task_id[:16]}..., retries={retry_count}"
                        )

                logger.info(
                    f"[JANITOR] Orphaned PENDING task recovery complete: "
                    f"re-sent={pending_requeued}, failed={pending_failed}"
                )
            else:
                logger.info("[JANITOR] No orphaned PENDING tasks found ✓")

            # ================================================================
            # SUMMARY
            # ================================================================
            logger.info(
                f"[JANITOR] ========== TASK WATCHDOG COMPLETE ==========\n"
                f"[JANITOR] Scanned: {result.items_scanned} tasks\n"
                f"[JANITOR] Fixed: {result.items_fixed} tasks\n"
                f"[JANITOR] Actions: {len(result.actions_taken)}"
            )
            result.complete(success=True)

        except Exception as e:
            logger.error(f"[JANITOR] Task watchdog failed: {e}")
            import traceback
            logger.error(f"[JANITOR] Traceback: {traceback.format_exc()}")
            result.complete(success=False, error=str(e))

        self._complete_run(result)
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
                    # Step 1: Get all tables in geo schema (excluding system tables)
                    # 21 JAN 2026: Exclude table_catalog and feature_collection_styles
                    cur.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'geo'
                        AND table_type = 'BASE TABLE'
                        AND table_name NOT IN ('table_catalog', 'table_metadata', 'feature_collection_styles')
                        ORDER BY table_name
                    """)
                    geo_tables = set(row['table_name'] for row in cur.fetchall())

                    # Step 2: Check if table_catalog exists (21 JAN 2026)
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_catalog'
                        )
                    """)
                    catalog_table_exists = cur.fetchone()['exists']

                    if not catalog_table_exists:
                        # No catalog table - all geo tables are orphaned
                        logger.warning("⚠️ GeoOrphanDetector: geo.table_catalog does not exist!")
                        for table_name in sorted(geo_tables):
                            try:
                                cur.execute(f'SELECT COUNT(*) FROM geo."{table_name}"')
                                row_count = cur.fetchone()['count']
                            except Exception:
                                row_count = None

                            result["orphaned_tables"].append({
                                "table_name": table_name,
                                "row_count": row_count,
                                "reason": "Table exists but geo.table_catalog does not exist"
                            })

                        result["summary"] = {
                            "total_geo_tables": len(geo_tables),
                            "total_catalog_records": 0,
                            "tracked": 0,
                            "orphaned_tables": len(geo_tables),
                            "orphaned_catalog": 0,
                            "health_status": "ORPHANS_DETECTED" if geo_tables else "HEALTHY",
                            "catalog_table_missing": True
                        }
                        result["success"] = True
                        result["duration_seconds"] = round(
                            (datetime.now(timezone.utc) - start_time).total_seconds(), 2
                        )
                        return result

                    # Step 3: Get all table names in catalog (21 JAN 2026)
                    cur.execute("""
                        SELECT table_name, created_at
                        FROM geo.table_catalog
                        ORDER BY table_name
                    """)
                    catalog_tables = {}
                    for row in cur.fetchall():
                        catalog_tables[row['table_name']] = {
                            'created_at': row['created_at'].isoformat() if row.get('created_at') else None
                        }

                    catalog_names = set(catalog_tables.keys())

                    # Step 4: Identify orphans
                    # Tables without catalog entry
                    orphaned_tables = geo_tables - catalog_names
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
                            "reason": "Table exists in geo schema but has no catalog record"
                        })

                    # Catalog entries without tables
                    orphaned_catalog = catalog_names - geo_tables
                    for table_name in sorted(orphaned_catalog):
                        cat = catalog_tables[table_name]
                        result["orphaned_metadata"].append({
                            "table_name": table_name,
                            "created_at": cat['created_at'],
                            "reason": "Catalog entry exists but table was dropped"
                        })

                    # Tracked (healthy) tables (21 JAN 2026: use catalog_names)
                    tracked = geo_tables & catalog_names
                    result["tracked_tables"] = sorted(tracked)

            # Build summary
            result["summary"] = {
                "total_geo_tables": len(geo_tables),
                "total_catalog_records": len(catalog_tables),
                "tracked": len(result["tracked_tables"]),
                "orphaned_tables": len(result["orphaned_tables"]),
                "orphaned_catalog": len(result["orphaned_metadata"]),
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
