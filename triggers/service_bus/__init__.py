# ============================================================================
# SERVICE BUS HANDLERS MODULE
# ============================================================================
# STATUS: Trigger layer - Service Bus message handling
# PURPOSE: Centralized handlers for Service Bus queue triggers
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 2 Service Bus Handler Extraction
# ============================================================================
"""
Service Bus Handlers Module.

Provides centralized handlers for all Service Bus queue triggers:
- handle_job_message: Process messages from geospatial-jobs queue
- handle_task_message: Process messages from functionapp-tasks and container-tasks queues

V0.8 Queue Architecture (24 JAN 2026):
- geospatial-jobs: Job orchestration + stage_complete signals
- functionapp-tasks: Lightweight ops (merged raster-tasks + vector-tasks)
- container-tasks: Heavy ops (Docker worker)

This module eliminates the ~400 lines of duplicate code that was previously
inline in function_app.py across Service Bus triggers.

Design Philosophy:
    - DRY: Single implementation for task handling
    - SEPARATION: Error handling extracted to error_handler.py
    - TRACEABILITY: Correlation IDs for log filtering

Usage in function_app.py:
    from triggers.service_bus import handle_job_message, handle_task_message

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="ServiceBusConnection"
    )
    def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
        handle_job_message(msg, core_machine)

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="functionapp-tasks",
        connection="ServiceBusConnection"
    )
    def process_functionapp_task(msg: func.ServiceBusMessage) -> None:
        handle_task_message(msg, core_machine, queue_name="functionapp-tasks")

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="container-tasks",
        connection="ServiceBusConnection"
    )
    def process_container_task(msg: func.ServiceBusMessage) -> None:
        handle_task_message(msg, core_machine, queue_name="container-tasks")

Exports:
    handle_job_message: Job queue handler
    handle_task_message: Task queue handler (raster + vector)
    extract_job_id_from_raw_message: Extract job_id from malformed message
    extract_task_id_from_raw_message: Extract task_id from malformed message
    mark_job_failed: Mark job as failed in database
    mark_task_failed: Mark task as failed in database
"""

from .job_handler import handle_job_message
from .task_handler import handle_task_message
from .error_handler import (
    extract_job_id_from_raw_message,
    extract_task_id_from_raw_message,
    mark_job_failed,
    mark_task_failed,
)

__all__ = [
    # Primary handlers
    'handle_job_message',
    'handle_task_message',
    # Error handling utilities
    'extract_job_id_from_raw_message',
    'extract_task_id_from_raw_message',
    'mark_job_failed',
    'mark_task_failed',
]
