# ============================================================================
# SERVICE BUS TASK HANDLER
# ============================================================================
# STATUS: Trigger layer - Task queue message processing
# PURPOSE: Handle messages from raster-tasks and vector-tasks queues
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 2 Service Bus Handler Extraction
# ============================================================================
"""
Task Queue Message Handler Module.

Handles messages from the raster-tasks and vector-tasks Service Bus queues.
Shared logic for both task types with queue-specific logging.

This module extracts the common task processing logic from function_app.py
to eliminate the 95% duplication between raster and vector task triggers.

Task Processing Flow:
    1. Log message receipt (GAP-1 fix)
    2. Parse TaskQueueMessage
    3. Update status: PENDING -> QUEUED
    4. Process via CoreMachine
    5. Log results and stage completion

Usage:
    from triggers.service_bus.task_handler import handle_task_message

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="raster-tasks",
        connection="ServiceBusConnection"
    )
    def process_raster_task(msg: func.ServiceBusMessage) -> None:
        handle_task_message(msg, core_machine, queue_name="raster-tasks")
"""

import time
import traceback
import uuid
from typing import Any, Dict

import azure.functions as func

from core.schema.queue import TaskQueueMessage
from core.models.enums import TaskStatus
from infrastructure import RepositoryFactory
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "TaskHandler")


def handle_task_message(
    msg: func.ServiceBusMessage,
    core_machine: Any,
    queue_name: str
) -> Dict[str, Any]:
    """
    Process a task message from Service Bus.

    Shared handler for both raster-tasks and vector-tasks queues.

    Args:
        msg: Service Bus message
        core_machine: CoreMachine instance for processing
        queue_name: Queue name for logging ("raster-tasks" or "vector-tasks")

    Returns:
        Processing result dict with success status and details
    """
    correlation_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    # GAP-1 FIX: Log Service Bus message metadata IMMEDIATELY
    _log_message_received(msg, correlation_id, queue_name)

    # Determine task type emoji for logging
    emoji = "" if queue_name == "raster-tasks" else ""
    task_type_label = "RASTER" if queue_name == "raster-tasks" else "VECTOR"

    logger.info(
        f"[{correlation_id}] {emoji} {task_type_label} TASK TRIGGER ({queue_name} queue)",
        extra={
            'checkpoint': f'{task_type_label}_TASK_TRIGGER_START',
            'correlation_id': correlation_id,
            'queue_name': queue_name
        }
    )

    try:
        # Parse message
        message_body = msg.get_body().decode('utf-8')
        task_message = TaskQueueMessage.model_validate_json(message_body)

        logger.info(
            f"[{correlation_id}] Parsed {task_type_label.lower()} task: "
            f"{task_message.task_id}, type={task_message.task_type}"
        )

        # Add correlation tracking
        if task_message.parameters is None:
            task_message.parameters = {}
        task_message.parameters['_correlation_id'] = correlation_id
        task_message.parameters['_processing_path'] = queue_name

        # PENDING -> QUEUED confirmation (proves message was delivered)
        _confirm_task_queued(task_message.task_id, correlation_id, queue_name)

        # Process via CoreMachine
        result = core_machine.process_task_message(task_message)

        elapsed = time.time() - start_time
        logger.info(f"[{correlation_id}] {task_type_label} task processed in {elapsed:.3f}s")
        logger.info(f"[{correlation_id}] Result: {result}")

        if result.get('stage_complete'):
            logger.info(
                f"[{correlation_id}] Stage {task_message.stage} complete "
                f"for job {task_message.parent_job_id[:16]}..."
            )

        return result

    except Exception as e:
        return _handle_exception(e, msg, correlation_id, start_time, queue_name)


def _log_message_received(
    msg: func.ServiceBusMessage,
    correlation_id: str,
    queue_name: str
) -> None:
    """Log Service Bus message metadata immediately on receipt."""
    logger.info(
        f"[{correlation_id}] SERVICE BUS MESSAGE RECEIVED ({queue_name})",
        extra={
            'checkpoint': 'MESSAGE_RECEIVED',
            'correlation_id': correlation_id,
            'queue_name': queue_name,
            'message_id': msg.message_id,
            'sequence_number': msg.sequence_number,
            'delivery_count': msg.delivery_count,
            'enqueued_time': msg.enqueued_time_utc.isoformat() if msg.enqueued_time_utc else None,
            'content_type': msg.content_type,
            'lock_token': str(msg.lock_token)[:16] if msg.lock_token else None
        }
    )


def _confirm_task_queued(
    task_id: str,
    correlation_id: str,
    queue_name: str
) -> None:
    """
    Update task status from PENDING to QUEUED.

    This confirms the message was received by the trigger, providing
    traceability for message delivery verification.

    Args:
        task_id: Task ID to update
        correlation_id: Correlation ID for logging
        queue_name: Queue name for logging
    """
    try:
        repos = RepositoryFactory.create_repositories()
        success = repos['task_repo'].update_task_status_with_validation(
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
            # Task may be in unexpected state - log but continue (janitor will handle)
            current = repos['task_repo'].get_task_status(task_id)
            logger.warning(
                f"[{correlation_id}] PENDING -> QUEUED update returned False. "
                f"Current status: {current}. Continuing (janitor will recover if needed)."
            )

    except Exception as status_error:
        logger.error(f"[{correlation_id}] Failed PENDING -> QUEUED update: {status_error}")
        # Continue processing - fail-safe, janitor will handle orphans


def _handle_exception(
    e: Exception,
    msg: func.ServiceBusMessage,
    correlation_id: str,
    start_time: float,
    queue_name: str
) -> Dict[str, Any]:
    """
    Handle exception during task processing.

    Logs the exception and attempts to mark the task/job as FAILED
    in the database to prevent stuck tasks.

    Args:
        e: The exception that occurred
        msg: Original Service Bus message
        correlation_id: Correlation ID for logging
        start_time: When processing started
        queue_name: Queue name for logging

    Returns:
        Error result dict
    """
    from .error_handler import extract_task_id_from_raw_message, mark_task_failed

    task_type_label = "raster" if queue_name == "raster-tasks" else "vector"

    elapsed = time.time() - start_time
    logger.error(f"[{correlation_id}] EXCEPTION in process_{task_type_label}_task after {elapsed:.3f}s")
    logger.error(f"[{correlation_id}] Exception type: {type(e).__name__}")
    logger.error(f"[{correlation_id}] Exception message: {e}")
    logger.error(f"[{correlation_id}] Full traceback:\n{traceback.format_exc()}")

    # Try to extract task_id/job_id and mark as failed
    message_body = msg.get_body().decode('utf-8') if msg else ''
    task_id, job_id = extract_task_id_from_raw_message(message_body, correlation_id)

    if task_id:
        logger.error(f"[{correlation_id}] Task ID: {task_id}")
    if job_id:
        logger.error(f"[{correlation_id}] Job ID: {job_id[:16]}...")

    if task_id or job_id:
        mark_task_failed(task_id, job_id, f"{type(e).__name__}: {e}", correlation_id)
    else:
        logger.error(f"[{correlation_id}] No task_id/job_id available - cannot mark as FAILED")
        logger.error(f"[{correlation_id}] Exception occurred before message parsing")

    logger.warning(f"[{correlation_id}] Function completing (failure logged and marked in DB)")

    return {
        "success": False,
        "error": str(e),
        "error_type": type(e).__name__,
        "correlation_id": correlation_id,
        "queue_name": queue_name,
    }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['handle_task_message']
