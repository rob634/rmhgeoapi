# ============================================================================
# SERVICE BUS ERROR HANDLER
# ============================================================================
# STATUS: Trigger layer - Queue error handling utilities
# PURPOSE: Extract and mark failed jobs/tasks from queue processing errors
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 2 Service Bus Handler Extraction
# ============================================================================
"""
Service Bus Error Handler Module.

Provides utilities for handling exceptions during queue message processing:
- Extract job/task IDs from potentially malformed messages
- Mark jobs/tasks as FAILED in the database
- Classify error types for diagnostics

These functions are used by job_handler.py and task_handler.py when
exceptions occur during message processing.

Usage:
    from triggers.service_bus.error_handler import (
        extract_job_id_from_raw_message,
        extract_task_id_from_raw_message,
        mark_job_failed,
        mark_task_failed,
    )

    # In exception handler
    job_id = extract_job_id_from_raw_message(message_body, correlation_id)
    if job_id:
        mark_job_failed(job_id, error_msg, correlation_id)
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueErrorHandler")


def extract_job_id_from_raw_message(
    message_content: str,
    correlation_id: str = "unknown"
) -> Optional[str]:
    """
    Try to extract job_id from potentially malformed message.

    Uses JSON parsing first, then regex as fallback. This allows
    job failure marking even when the message can't be fully parsed.

    Args:
        message_content: Raw message content that may be malformed
        correlation_id: Correlation ID for logging

    Returns:
        job_id if found, None otherwise
    """
    # Try JSON parsing first
    try:
        data = json.loads(message_content)
        job_id = data.get('job_id')
        if job_id:
            logger.info(f"[{correlation_id}] Extracted job_id via JSON: {job_id[:16]}...")
            return job_id
    except Exception:
        pass  # Try regex next

    # Try regex as fallback
    try:
        match = re.search(r'"job_id"\s*:\s*"([^"]+)"', message_content)
        if match:
            job_id = match.group(1)
            logger.info(f"[{correlation_id}] Extracted job_id via regex: {job_id[:16]}...")
            return job_id
    except Exception:
        pass

    logger.warning(f"[{correlation_id}] Could not extract job_id from message")
    return None


def extract_task_id_from_raw_message(
    message_content: str,
    correlation_id: str = "unknown"
) -> Tuple[Optional[str], Optional[str]]:
    """
    Try to extract task_id and parent_job_id from potentially malformed message.

    Uses JSON parsing first, then regex as fallback.

    Args:
        message_content: Raw message content that may be malformed
        correlation_id: Correlation ID for logging

    Returns:
        Tuple of (task_id, parent_job_id) if found, (None, None) otherwise
    """
    task_id = None
    parent_job_id = None

    # Try JSON parsing first
    try:
        data = json.loads(message_content)
        task_id = data.get('task_id')
        parent_job_id = data.get('parent_job_id')

        if task_id:
            logger.info(f"[{correlation_id}] Extracted task_id via JSON: {task_id}")
        if parent_job_id:
            logger.info(f"[{correlation_id}] Extracted parent_job_id via JSON: {parent_job_id[:16]}...")

    except Exception:
        # Try regex as fallback
        try:
            task_match = re.search(r'"task_id"\s*:\s*"([^"]+)"', message_content)
            if task_match:
                task_id = task_match.group(1)
                logger.info(f"[{correlation_id}] Extracted task_id via regex: {task_id}")

            job_match = re.search(r'"parent_job_id"\s*:\s*"([^"]+)"', message_content)
            if job_match:
                parent_job_id = job_match.group(1)
                logger.info(f"[{correlation_id}] Extracted parent_job_id via regex: {parent_job_id[:16]}...")
        except Exception:
            pass

    if not task_id and not parent_job_id:
        logger.warning(f"[{correlation_id}] Could not extract task_id or parent_job_id from message")

    return task_id, parent_job_id


def mark_job_failed(
    job_id: str,
    error_msg: str,
    correlation_id: str = "unknown"
) -> bool:
    """
    Mark a job as FAILED in the database.

    Called when queue processing fails to ensure jobs don't get stuck.

    Args:
        job_id: Job ID to mark as failed
        error_msg: Error message to record
        correlation_id: Correlation ID for logging

    Returns:
        True if successfully marked, False otherwise
    """
    try:
        from infrastructure import RepositoryFactory
        from core.models.enums import JobStatus

        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']

        # Check if job exists and isn't already terminal
        job = job_repo.get_job(job_id)

        if not job:
            logger.error(f"[{correlation_id}] Job {job_id[:16]}... not found in database")
            return False

        if job.status in [JobStatus.FAILED, JobStatus.COMPLETED]:
            logger.info(f"[{correlation_id}] Job {job_id[:16]}... already {job.status.value}")
            return True

        # Mark as failed
        job_repo.update_job_status_with_validation(
            job_id=job_id,
            new_status=JobStatus.FAILED,
            additional_updates={
                'error_details': f"Queue processing error: {error_msg}",
                'failed_at': datetime.now(timezone.utc).isoformat(),
                'queue_correlation_id': correlation_id
            }
        )

        logger.info(f"[{correlation_id}] Job {job_id[:16]}... marked as FAILED")
        return True

    except Exception as e:
        logger.error(f"[{correlation_id}] Failed to mark job {job_id[:16]}... as failed: {e}")
        return False


def mark_task_failed(
    task_id: Optional[str],
    parent_job_id: Optional[str],
    error_msg: str,
    correlation_id: str = "unknown"
) -> bool:
    """
    Mark a task (and optionally its parent job) as FAILED in the database.

    Called when queue processing fails to ensure tasks don't get stuck.

    Args:
        task_id: Task ID to mark as failed (may be None)
        parent_job_id: Parent job ID to also mark as failed (may be None)
        error_msg: Error message to record
        correlation_id: Correlation ID for logging

    Returns:
        True if at least one entity was marked, False if both failed
    """
    success = False

    try:
        from infrastructure import RepositoryFactory
        from core.models.enums import TaskStatus
        from core.models.task import TaskUpdateModel

        repos = RepositoryFactory.create_repositories()

        # Mark task as failed
        if task_id:
            task_repo = repos['task_repo']
            task = task_repo.get_task(task_id)

            if task and task.status not in [TaskStatus.FAILED, TaskStatus.COMPLETED]:
                update = TaskUpdateModel(
                    status=TaskStatus.FAILED,
                    error_details=f"Queue processing error: {error_msg}"
                )
                task_repo.update_task(task_id=task_id, updates=update)
                logger.info(f"[{correlation_id}] Task {task_id} marked as FAILED")
                success = True

            elif task and task.status == TaskStatus.FAILED:
                logger.info(f"[{correlation_id}] Task {task_id} already FAILED")
                success = True

            elif task and task.status == TaskStatus.COMPLETED:
                logger.warning(f"[{correlation_id}] Task {task_id} is COMPLETED but queue error occurred")

            else:
                logger.error(f"[{correlation_id}] Task {task_id} not found in database")

        # Mark parent job as failed
        if parent_job_id:
            task_ref = task_id[:16] if task_id else 'unknown'
            if mark_job_failed(
                parent_job_id,
                f"Task {task_ref}... failed: {error_msg}",
                correlation_id
            ):
                success = True

    except Exception as e:
        logger.error(f"[{correlation_id}] Failed to mark task/job as failed: {e}")

    if not success:
        logger.error(f"[{correlation_id}] Task/Job may be stuck - janitor will recover after timeout")

    return success


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'extract_job_id_from_raw_message',
    'extract_task_id_from_raw_message',
    'mark_job_failed',
    'mark_task_failed',
]
