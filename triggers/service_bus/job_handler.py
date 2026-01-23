# ============================================================================
# SERVICE BUS JOB HANDLER
# ============================================================================
# STATUS: Trigger layer - Job queue message processing
# PURPOSE: Handle messages from geospatial-jobs queue
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 2 Service Bus Handler Extraction
# ============================================================================
"""
Job Queue Message Handler Module.

Handles messages from the geospatial-jobs Service Bus queue:
- job_submit: New job or stage advancement
- stage_complete: Signal from worker app that a stage finished

This module extracts the common job processing logic from function_app.py
to eliminate duplication and improve maintainability.

Usage:
    from triggers.service_bus.job_handler import handle_job_message

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="ServiceBusConnection"
    )
    def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
        handle_job_message(msg, core_machine)
"""

import json
import time
import traceback
import uuid
from typing import Any, Dict

import azure.functions as func

from core.schema.queue import JobQueueMessage
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "JobHandler")


def handle_job_message(
    msg: func.ServiceBusMessage,
    core_machine: Any
) -> Dict[str, Any]:
    """
    Process a job message from Service Bus.

    Handles two message types:
    - job_submit (default): New job or stage advancement - creates tasks
    - stage_complete: Signal from worker app that a stage finished

    Args:
        msg: Service Bus message
        core_machine: CoreMachine instance for processing

    Returns:
        Processing result dict with success status and details
    """
    correlation_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    # GAP-1 FIX: Log Service Bus message metadata IMMEDIATELY
    _log_message_received(msg, correlation_id)

    logger.info(
        f"[{correlation_id}] COREMACHINE JOB TRIGGER (Service Bus)",
        extra={
            'checkpoint': 'JOB_TRIGGER_START',
            'correlation_id': correlation_id,
            'trigger_type': 'service_bus',
            'queue_name': 'geospatial-jobs'
        }
    )

    try:
        # Extract message body (no base64 decoding needed for Service Bus)
        message_body = msg.get_body().decode('utf-8')
        logger.info(
            f"[{correlation_id}] Message size: {len(message_body)} bytes",
            extra={
                'checkpoint': 'JOB_TRIGGER_RECEIVE_MESSAGE',
                'correlation_id': correlation_id,
                'message_size_bytes': len(message_body)
            }
        )

        # Parse as generic dict first to check message_type
        message_dict = json.loads(message_body)
        message_type = message_dict.get('message_type', 'job_submit')

        if message_type == 'stage_complete':
            result = _handle_stage_complete(message_dict, core_machine, correlation_id)
        else:
            result = _handle_job_submit(message_body, core_machine, correlation_id)

        elapsed = time.time() - start_time
        logger.info(f"[{correlation_id}] CoreMachine processed in {elapsed:.3f}s")
        logger.info(f"[{correlation_id}] Result: {result}")

        return result

    except Exception as e:
        return _handle_exception(e, msg, correlation_id, start_time)


def _log_message_received(msg: func.ServiceBusMessage, correlation_id: str) -> None:
    """Log Service Bus message metadata immediately on receipt."""
    logger.info(
        f"[{correlation_id}] SERVICE BUS MESSAGE RECEIVED (geospatial-jobs)",
        extra={
            'checkpoint': 'MESSAGE_RECEIVED',
            'correlation_id': correlation_id,
            'queue_name': 'geospatial-jobs',
            'message_id': msg.message_id,
            'sequence_number': msg.sequence_number,
            'delivery_count': msg.delivery_count,
            'enqueued_time': msg.enqueued_time_utc.isoformat() if msg.enqueued_time_utc else None,
            'content_type': msg.content_type,
            'lock_token': str(msg.lock_token)[:16] if msg.lock_token else None
        }
    )


def _handle_stage_complete(
    message_dict: dict,
    core_machine: Any,
    correlation_id: str
) -> dict:
    """
    Handle stage_complete message from worker app.

    Args:
        message_dict: Parsed message as dict
        core_machine: CoreMachine instance
        correlation_id: Correlation ID for logging

    Returns:
        Processing result dict
    """
    logger.info(
        f"[{correlation_id}] Processing stage_complete message from worker",
        extra={
            'checkpoint': 'JOB_TRIGGER_STAGE_COMPLETE',
            'correlation_id': correlation_id,
            'job_id': message_dict.get('job_id', 'unknown')[:16],
            'completed_stage': message_dict.get('completed_stage'),
            'completed_by_app': message_dict.get('completed_by_app', 'unknown')
        }
    )
    return core_machine.process_stage_complete_message(message_dict)


def _handle_job_submit(
    message_body: str,
    core_machine: Any,
    correlation_id: str
) -> dict:
    """
    Handle job_submit message (new job or stage advancement).

    Args:
        message_body: Raw message body as JSON string
        core_machine: CoreMachine instance
        correlation_id: Correlation ID for logging

    Returns:
        Processing result dict
    """
    job_message = JobQueueMessage.model_validate_json(message_body)

    logger.info(
        f"[{correlation_id}] Parsed job: {job_message.job_id[:16]}..., type={job_message.job_type}",
        extra={
            'checkpoint': 'JOB_TRIGGER_PARSE_SUCCESS',
            'correlation_id': correlation_id,
            'job_id': job_message.job_id,
            'job_type': job_message.job_type,
            'stage': job_message.stage
        }
    )

    # Add correlation ID for tracking
    if job_message.parameters is None:
        job_message.parameters = {}
    job_message.parameters['_correlation_id'] = correlation_id
    job_message.parameters['_processing_path'] = 'service_bus'

    return core_machine.process_job_message(job_message)


def _handle_exception(
    e: Exception,
    msg: func.ServiceBusMessage,
    correlation_id: str,
    start_time: float
) -> Dict[str, Any]:
    """
    Handle exception during job processing.

    Logs the exception and attempts to mark the job as FAILED in the database
    to prevent stuck jobs.

    Args:
        e: The exception that occurred
        msg: Original Service Bus message
        correlation_id: Correlation ID for logging
        start_time: When processing started

    Returns:
        Error result dict
    """
    from .error_handler import extract_job_id_from_raw_message, mark_job_failed

    elapsed = time.time() - start_time
    logger.error(f"[{correlation_id}] EXCEPTION in process_service_bus_job after {elapsed:.3f}s")
    logger.error(f"[{correlation_id}] Exception type: {type(e).__name__}")
    logger.error(f"[{correlation_id}] Exception message: {e}")
    logger.error(f"[{correlation_id}] Full traceback:\n{traceback.format_exc()}")

    # Try to extract job_id and mark as failed
    message_body = msg.get_body().decode('utf-8') if msg else ''
    job_id = extract_job_id_from_raw_message(message_body, correlation_id)

    if job_id:
        logger.error(f"[{correlation_id}] Job ID: {job_id}")
        mark_job_failed(job_id, f"{type(e).__name__}: {e}", correlation_id)
    else:
        logger.error(f"[{correlation_id}] No job_id available - cannot mark job as FAILED")
        logger.error(f"[{correlation_id}] Exception occurred before message parsing")

    # Job processing errors are typically critical (workflow creation failures)
    # Log extensively but don't re-raise to avoid Service Bus retries
    logger.warning(f"[{correlation_id}] Function completing (exception logged but not re-raised)")
    logger.warning(f"[{correlation_id}] Job failure handling complete")

    return {
        "success": False,
        "error": str(e),
        "error_type": type(e).__name__,
        "correlation_id": correlation_id,
    }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['handle_job_message']
