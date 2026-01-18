#!/usr/bin/env python3
# ============================================================================
# CLAUDE CONTEXT - DOCKER WORKER ENTRY POINT
# ============================================================================
# STATUS: Core Component - Service Bus polling loop for Docker deployment
# PURPOSE: Process long-running tasks from long-running-tasks queue
# LAST_REVIEWED: 10 JAN 2026
# ============================================================================
"""
Docker Worker Entry Point.

Polls the long-running-tasks queue and processes tasks via CoreMachine.
This replaces function_app.py for Docker deployments.

Key Differences from Azure Functions:
    - No automatic message completion (we control it)
    - No timeout constraints (can run for hours)
    - Graceful shutdown handling for container orchestration
    - Direct Service Bus SDK usage for receiver control

Usage:
    APP_MODE=worker_docker python docker_main.py

Environment Variables (Required):
    APP_MODE=worker_docker
    APP_NAME=docker-worker-01
    ServiceBusConnection=<connection-string> OR SERVICE_BUS_NAMESPACE=<namespace>
    POSTGIS_HOST, POSTGIS_DATABASE, etc.

Architecture:
    This worker uses the SAME CoreMachine contract as Azure Functions.
    The only difference is WHO polls the queue and manages message lifecycle.

    Function App:  Azure runtime polls → ServiceBusTrigger → process_task_message
    Docker Worker: docker_main.py polls → process_task_message → complete/dead-letter
"""

import os
import sys
import time
import json
import signal
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

# Ensure APP_MODE is set before importing config
os.environ.setdefault("APP_MODE", "worker_docker")


# ============================================================================
# AZURE MONITOR OPENTELEMETRY SETUP (MUST BE EARLY)
# ============================================================================
# This sends logs, traces, and metrics to Application Insights - giving Docker
# workers the same observability as Azure Functions.
# ============================================================================

def _configure_azure_monitor():
    """Configure Azure Monitor OpenTelemetry for Docker queue worker."""
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")

    if not connection_string:
        print("⚠️ APPLICATIONINSIGHTS_CONNECTION_STRING not set - telemetry disabled")
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        app_name = os.environ.get("APP_NAME", "docker-worker")
        environment = os.environ.get("ENVIRONMENT", "dev")

        configure_azure_monitor(
            connection_string=connection_string,
            resource_attributes={
                "service.name": app_name,
                "service.namespace": "rmhgeoapi",
                "deployment.environment": environment,
            },
            enable_live_metrics=True,
        )

        print(f"✅ Azure Monitor OpenTelemetry configured (app={app_name}, env={environment})")
        return True

    except ImportError:
        print("⚠️ azure-monitor-opentelemetry not installed - telemetry disabled")
        return False
    except Exception as e:
        print(f"⚠️ Azure Monitor setup failed: {e} - telemetry disabled")
        return False


_azure_monitor_enabled = _configure_azure_monitor()


# Azure SDK imports
from azure.servicebus import ServiceBusClient, ServiceBusReceiver, ServiceBusReceivedMessage, AutoLockRenewer
from azure.servicebus.exceptions import (
    ServiceBusError,
    ServiceBusConnectionError,
    OperationTimeoutError,
)
from azure.identity import DefaultAzureCredential

# Application imports
from config import get_config
from config.app_mode_config import get_app_mode_config
from core.machine import CoreMachine
from core.schema.queue import TaskQueueMessage
from jobs import ALL_JOBS
from services import ALL_HANDLERS
from util_logger import LoggerFactory, ComponentType

# Module-level logger
logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "DockerWorker")

# Graceful shutdown flag
_shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


class DockerWorker:
    """
    Docker Worker for long-running geospatial tasks.

    Polls the long-running-tasks Service Bus queue and processes tasks
    via CoreMachine, identical to how Azure Functions process tasks.

    Key Features:
        - No timeout constraints (Docker containers can run for hours)
        - Graceful shutdown handling (SIGTERM/SIGINT)
        - Same CoreMachine processing as Azure Functions
        - Stage completion signaling to jobs queue
    """

    def __init__(self):
        """Initialize the Docker worker."""
        # Load configuration
        self.config = get_config()
        self.app_mode_config = get_app_mode_config()

        # Validate we're in Docker mode
        if not self.app_mode_config.is_docker_mode:
            raise ValueError(
                f"Invalid APP_MODE: {self.app_mode_config.mode.value}. "
                f"Docker worker requires APP_MODE=worker_docker"
            )

        # Initialize CoreMachine with explicit registries
        self.core_machine = CoreMachine(
            all_jobs=ALL_JOBS,
            all_handlers=ALL_HANDLERS
        )

        # Service Bus client (lazy init)
        self._sb_client: Optional[ServiceBusClient] = None

        # Configuration
        self.queue_name = self.config.queues.long_running_tasks_queue
        self.app_name = self.app_mode_config.app_name

        # Processing settings
        self.max_wait_time_seconds = 30  # Long poll - wait up to 30s for messages
        self.poll_interval_on_error = 5  # Seconds to wait after error before retrying

        logger.info("=" * 70)
        logger.info("Docker Worker Initialized")
        logger.info(f"  App Name: {self.app_name}")
        logger.info(f"  Queue: {self.queue_name}")
        logger.info(f"  Database: {self.config.database.host}")
        logger.info(f"  Handlers: {len(ALL_HANDLERS)} registered")
        logger.info(f"  Jobs: {len(ALL_JOBS)} registered")
        logger.info("=" * 70)

    def _get_sb_client(self) -> ServiceBusClient:
        """
        Get or create Service Bus client.

        Supports both connection string and Managed Identity authentication.
        """
        if self._sb_client is None:
            connection_string = self.config.queues.connection_string

            if connection_string:
                logger.info("Using Service Bus connection string authentication")
                self._sb_client = ServiceBusClient.from_connection_string(connection_string)
            else:
                # Managed Identity
                namespace = self.config.queues.namespace
                if not namespace:
                    raise ValueError(
                        "No Service Bus connection configured. "
                        "Set ServiceBusConnection or SERVICE_BUS_NAMESPACE"
                    )
                logger.info(f"Using Managed Identity authentication for Service Bus: {namespace}")
                credential = DefaultAzureCredential()
                self._sb_client = ServiceBusClient(
                    fully_qualified_namespace=namespace,
                    credential=credential
                )

        return self._sb_client

    def _process_message(
        self,
        message: ServiceBusReceivedMessage,
        receiver: ServiceBusReceiver
    ) -> bool:
        """
        Process a single message via CoreMachine.

        Args:
            message: The Service Bus message
            receiver: The receiver (for completing/abandoning)

        Returns:
            True if processed successfully, False otherwise
        """
        start_time = time.time()
        task_id = "unknown"

        try:
            # Parse message body
            message_body = str(message)
            task_data = json.loads(message_body)

            # Create TaskQueueMessage
            task_message = TaskQueueMessage(**task_data)
            task_id = task_message.task_id

            logger.info(
                f"Processing task: {task_id[:16]}... "
                f"(type: {task_message.task_type}, "
                f"job: {task_message.parent_job_id[:16]}..., "
                f"stage: {task_message.stage})"
            )

            # Process via CoreMachine (same as Function App)
            result = self.core_machine.process_task_message(task_message)

            elapsed = time.time() - start_time

            if result.get('success'):
                logger.info(f"Task completed in {elapsed:.2f}s: {task_id[:16]}...")
                receiver.complete_message(message)

                if result.get('stage_complete'):
                    logger.info(
                        f"Stage {task_message.stage} complete for job "
                        f"{task_message.parent_job_id[:16]}... - signaled to jobs queue"
                    )
                return True
            else:
                error = result.get('error', 'Unknown error')
                logger.error(f"Task failed after {elapsed:.2f}s: {error}")
                # Dead-letter failed messages after all retries exhausted
                receiver.dead_letter_message(
                    message,
                    reason="TaskFailed",
                    error_description=str(error)[:1024]  # Truncate to avoid size issues
                )
                return False

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message JSON: {e}")
            receiver.dead_letter_message(
                message,
                reason="JSONDecodeError",
                error_description=str(e)
            )
            return False

        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(f"Exception processing task {task_id[:16]}... after {elapsed:.2f}s: {e}")
            # Abandon to allow retry (Service Bus will eventually dead-letter after max retries)
            try:
                receiver.abandon_message(message)
            except Exception as abandon_err:
                logger.error(f"Failed to abandon message: {abandon_err}")
            return False

    def run(self):
        """
        Main polling loop.

        Runs until shutdown signal is received.
        """
        global _shutdown_requested

        logger.info(f"Starting main polling loop on queue: {self.queue_name}")
        logger.info("Waiting for messages... (Ctrl+C to stop)")

        client = self._get_sb_client()

        # Create AutoLockRenewer for long-running tasks (up to 2 hours)
        # This prevents competing consumers during lengthy COG processing
        lock_renewer = AutoLockRenewer(max_lock_renewal_duration=7200)  # 2 hours in seconds
        logger.info("AutoLockRenewer initialized (max_lock_renewal_duration=2h)")

        while not _shutdown_requested:
            try:
                # Create receiver with auto lock renewal for long-running tasks
                with client.get_queue_receiver(
                    queue_name=self.queue_name,
                    max_wait_time=self.max_wait_time_seconds,
                    auto_lock_renewer=lock_renewer,
                ) as receiver:

                    # Receive one message at a time for long-running tasks
                    messages = receiver.receive_messages(
                        max_message_count=1,
                        max_wait_time=self.max_wait_time_seconds
                    )

                    if not messages:
                        # No messages, continue polling
                        continue

                    for message in messages:
                        if _shutdown_requested:
                            logger.info("Shutdown requested, abandoning current message")
                            receiver.abandon_message(message)
                            break

                        self._process_message(message, receiver)

            except (ServiceBusConnectionError, OperationTimeoutError) as e:
                # Transient errors - log and retry
                logger.warning(f"Transient Service Bus error: {type(e).__name__}: {e}")
                if not _shutdown_requested:
                    time.sleep(self.poll_interval_on_error)

            except ServiceBusError as e:
                logger.error(f"Service Bus error: {type(e).__name__}: {e}")
                if not _shutdown_requested:
                    time.sleep(self.poll_interval_on_error)

            except Exception as e:
                logger.exception(f"Unexpected error in polling loop: {e}")
                if not _shutdown_requested:
                    time.sleep(self.poll_interval_on_error)

        # Cleanup
        logger.info("Shutting down...")
        lock_renewer.close()
        if self._sb_client:
            self._sb_client.close()

        logger.info("Docker Worker shutdown complete")
        logger.info(f"Shutdown at: {datetime.now(timezone.utc).isoformat()}")

    def close(self):
        """Clean up resources."""
        if self._sb_client:
            self._sb_client.close()
            self._sb_client = None


def main():
    """Entry point for Docker worker."""
    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        worker = DockerWorker()
        worker.run()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
