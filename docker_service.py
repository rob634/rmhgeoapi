#!/usr/bin/env python3
# ============================================================================
# CLAUDE CONTEXT - DOCKER SERVICE (HTTP + Queue Worker)
# ============================================================================
# STATUS: Core Component - Docker container with HTTP API and queue processing
# PURPOSE: Health checks + Service Bus queue polling for long-running tasks
# LAST_REVIEWED: 16 JAN 2026
# F7.18: Added DockerWorkerLifecycle, graceful shutdown, shared shutdown event
# ============================================================================
"""
Docker Service - HTTP API + Background Queue Worker.

This module runs:
    1. FastAPI HTTP server (for health checks and diagnostics)
    2. Background thread polling Service Bus queue for long-running tasks

The queue worker uses CoreMachine.process_task_message() - identical to how
Azure Functions process tasks. The only difference is the trigger mechanism.

HTTP Endpoints:
    /livez       - Liveness probe (is the process running?)
    /readyz      - Readiness probe (can we serve traffic?)
    /health      - Detailed health (token status, connectivity, queue status)
    /queue/status - Queue worker status

Background Services:
    - Token refresh thread (PostgreSQL + Storage OAuth every 45 min)
    - Queue polling thread (polls long-running-tasks queue)

Usage:
    # Start the server (includes background queue worker)
    uvicorn docker_service:app --host 0.0.0.0 --port 80

    # Test endpoints
    curl http://localhost/livez
    curl http://localhost/readyz
    curl http://localhost/health
    curl http://localhost/queue/status
"""

import os
import sys
import time
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Ensure APP_MODE is set
os.environ.setdefault("APP_MODE", "worker_docker")


# ============================================================================
# AZURE MONITOR OPENTELEMETRY SETUP (MUST BE BEFORE FASTAPI IMPORT)
# ============================================================================
# This sends logs, traces, and metrics to Application Insights - giving Docker
# workers the same observability as Azure Functions.
#
# CRITICAL: configure_azure_monitor() must be called BEFORE importing FastAPI
# otherwise the instrumentation won't capture FastAPI requests properly.
#
# Requires: APPLICATIONINSIGHTS_CONNECTION_STRING environment variable
# ============================================================================

def configure_azure_monitor_telemetry():
    """
    Configure Azure Monitor OpenTelemetry for Docker environment.

    This enables:
    - Logs → Application Insights traces table
    - HTTP requests → Application Insights requests table
    - Exceptions → Application Insights exceptions table
    - Custom metrics → Application Insights customMetrics table

    Authentication:
    - If APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD is set,
      uses DefaultAzureCredential (Managed Identity) for Entra ID auth.
    - Otherwise uses connection string auth (requires local auth enabled on App Insights).

    Falls back gracefully if package not installed or connection string missing.
    """
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")

    if not connection_string:
        print("⚠️ APPLICATIONINSIGHTS_CONNECTION_STRING not set - telemetry disabled")
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        # Get app identification for log correlation
        app_name = os.environ.get("APP_NAME", "docker-worker")
        environment = os.environ.get("ENVIRONMENT", "dev")

        # Check if AAD authentication is required (21 JAN 2026)
        # App Insights may have DisableLocalAuth=true, requiring Entra ID auth
        auth_string = os.environ.get("APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "")
        use_aad_auth = "Authorization=AAD" in auth_string

        configure_kwargs = {
            "connection_string": connection_string,
            "resource_attributes": {
                "service.name": app_name,
                "service.namespace": "rmhgeoapi",
                "deployment.environment": environment,
            },
            "enable_live_metrics": True,
        }

        if use_aad_auth:
            # Use Managed Identity for Entra ID authentication
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            configure_kwargs["credential"] = credential
            print(f"🔐 Using Entra ID (AAD) authentication for Application Insights")

        configure_azure_monitor(**configure_kwargs)

        auth_mode = "AAD" if use_aad_auth else "connection_string"
        print(f"✅ Azure Monitor OpenTelemetry configured (app={app_name}, env={environment}, auth={auth_mode})")
        return True

    except ImportError:
        print("⚠️ azure-monitor-opentelemetry not installed - telemetry disabled")
        return False
    except Exception as e:
        print(f"⚠️ Azure Monitor setup failed: {e} - telemetry disabled")
        return False


# Configure Azure Monitor BEFORE any other imports
_azure_monitor_enabled = configure_azure_monitor_telemetry()


# ============================================================================
# LOGGING SETUP
# ============================================================================

def configure_docker_logging():
    """Configure logging for Docker environment."""
    import logging

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # If Azure Monitor is configured, it adds its own handler
    # We still add a stream handler for local visibility
    if not _azure_monitor_enabled:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    for logger_name in ['uvicorn', 'uvicorn.error', 'uvicorn.access']:
        uvi_logger = logging.getLogger(logger_name)
        uvi_logger.handlers = []
        uvi_logger.addHandler(handler)
        uvi_logger.propagate = False

    # CRITICAL: Suppress verbose Azure SDK logs that drown out application logs
    # Match function_app.py settings (21 JAN 2026)
    logging.getLogger("azure.identity").setLevel(logging.WARNING)
    logging.getLogger("azure.identity._internal").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.storage").setLevel(logging.WARNING)
    logging.getLogger("azure.core").setLevel(logging.WARNING)
    logging.getLogger("azure.servicebus").setLevel(logging.WARNING)
    logging.getLogger("azure.servicebus._pyamqp").setLevel(logging.WARNING)
    logging.getLogger("azure.monitor.opentelemetry").setLevel(logging.WARNING)
    logging.getLogger("msal").setLevel(logging.WARNING)


configure_docker_logging()

import json
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Azure Service Bus imports for queue polling
from azure.servicebus import ServiceBusClient, ServiceBusReceiver, ServiceBusReceivedMessage, AutoLockRenewer
from azure.servicebus.exceptions import (
    ServiceBusError,
    ServiceBusConnectionError,
    OperationTimeoutError,
)
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


# ============================================================================
# DOCKER WORKER LIFECYCLE (F7.18 - Graceful Shutdown)
# ============================================================================

class DockerWorkerLifecycle:
    """
    Manages Docker worker lifecycle with graceful shutdown support.

    Provides:
    - Shared shutdown event for all components
    - SIGTERM/SIGINT signal handling
    - Coordinated shutdown across workers and connection pool

    Usage:
        lifecycle = DockerWorkerLifecycle()
        lifecycle.register_signal_handlers()

        # Workers use lifecycle.shutdown_event
        queue_worker = BackgroundQueueWorker(shutdown_event=lifecycle.shutdown_event)

        # On SIGTERM, lifecycle.initiate_shutdown() is called automatically
        # All workers receive the shutdown signal and save checkpoints
    """

    def __init__(self):
        self._shutdown_event = threading.Event()
        self._shutdown_initiated = False
        self._shutdown_initiated_at: Optional[datetime] = None
        self._signal_received: Optional[str] = None

    @property
    def shutdown_event(self) -> threading.Event:
        """Shared shutdown event for all components."""
        return self._shutdown_event

    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown has been initiated."""
        return self._shutdown_initiated

    def register_signal_handlers(self) -> None:
        """
        Register SIGTERM and SIGINT handlers for graceful shutdown.

        SIGTERM: Sent by Docker/Kubernetes when stopping container
        SIGINT: Sent when pressing Ctrl+C (useful for local dev)

        These signals trigger initiate_shutdown() which:
        1. Sets the shutdown event
        2. Allows in-flight tasks to save checkpoints
        3. Drains connection pool
        """
        import signal

        def shutdown_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            logger.warning(f"🛑 Received {signal_name} - initiating graceful shutdown")
            self.initiate_shutdown(signal_name)

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)
        logger.info("📡 Signal handlers registered (SIGTERM, SIGINT)")

    def initiate_shutdown(self, reason: str = "manual") -> None:
        """
        Initiate graceful shutdown.

        Sets the shutdown event which signals:
        - BackgroundQueueWorker to stop accepting new messages
        - Active tasks to save checkpoints (via DockerTaskContext.should_stop())
        - ConnectionPoolManager to drain and close

        Args:
            reason: Why shutdown was initiated (for logging)
        """
        if self._shutdown_initiated:
            logger.warning(f"🛑 Shutdown already initiated, ignoring duplicate request: {reason}")
            return

        self._shutdown_initiated = True
        self._shutdown_initiated_at = datetime.now(timezone.utc)
        self._signal_received = reason

        logger.warning("=" * 60)
        logger.warning(f"🛑 GRACEFUL SHUTDOWN INITIATED: {reason}")
        logger.warning(f"   Timestamp: {self._shutdown_initiated_at.isoformat()}")
        logger.warning("=" * 60)
        logger.info("  → Setting shutdown event for all components")
        self._shutdown_event.set()
        logger.info("  → Shutdown event SET - workers will stop accepting new messages")

        # Drain connection pool (F7.18 integration)
        try:
            from infrastructure.connection_pool import ConnectionPoolManager
            logger.info("  → Shutting down connection pool...")
            ConnectionPoolManager.shutdown()
            logger.info("  → Connection pool shutdown complete")
        except Exception as e:
            logger.warning(f"  → Connection pool shutdown error (non-fatal): {e}")

        logger.info("  → Graceful shutdown initiated - waiting for in-flight tasks to complete")

    def get_status(self) -> Dict[str, Any]:
        """Get lifecycle status for health endpoint."""
        status = {
            "shutdown_initiated": self._shutdown_initiated,
            "shutdown_event_set": self._shutdown_event.is_set(),
        }

        if self._shutdown_initiated:
            status["shutdown_initiated_at"] = self._shutdown_initiated_at.isoformat()
            status["shutdown_reason"] = self._signal_received
            if self._shutdown_initiated_at:
                elapsed = (datetime.now(timezone.utc) - self._shutdown_initiated_at).total_seconds()
                status["shutdown_elapsed_seconds"] = round(elapsed, 1)

        return status


# Global lifecycle manager (singleton)
worker_lifecycle = DockerWorkerLifecycle()


# ============================================================================
# BACKGROUND TOKEN REFRESH
# ============================================================================

class TokenRefreshWorker:
    """Background worker that refreshes OAuth tokens periodically."""

    def __init__(
        self,
        interval_seconds: int = 45 * 60,
        shutdown_event: Optional[threading.Event] = None
    ):
        self._thread: Optional[threading.Thread] = None
        # Use shared shutdown event if provided, otherwise create own
        self._stop_event = shutdown_event if shutdown_event else threading.Event()
        self._uses_shared_event = shutdown_event is not None
        self._interval = interval_seconds
        self._last_refresh: Optional[datetime] = None
        self._refresh_count = 0

    def _run_loop(self):
        """Background refresh loop."""
        from infrastructure.auth import refresh_all_tokens

        logger.info(f"[Token Refresh] Starting (interval: {self._interval}s)")

        while not self._stop_event.is_set():
            # Wait for interval (interruptible)
            if self._stop_event.wait(timeout=self._interval):
                break  # Stop event was set

            # Refresh tokens
            try:
                logger.info("[Token Refresh] Refreshing tokens...")
                status = refresh_all_tokens()
                self._last_refresh = datetime.now(timezone.utc)
                self._refresh_count += 1
                logger.info(f"[Token Refresh] Complete: {status}")
            except Exception as e:
                logger.error(f"[Token Refresh] Error: {e}")

        logger.info("[Token Refresh] Stopped")

    def start(self):
        """Start the background thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        # Only clear event if we own it (not shared)
        if not self._uses_shared_event:
            self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[Token Refresh] Background thread started")

    def stop(self):
        """Stop the background thread."""
        # Only set event if we own it (shared event is set by lifecycle)
        if not self._uses_shared_event:
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def get_status(self) -> dict:
        """Get refresh status."""
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "interval_seconds": self._interval,
            "refresh_count": self._refresh_count,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "uses_shared_shutdown": self._uses_shared_event,
        }


# ============================================================================
# BACKGROUND QUEUE WORKER (Service Bus Polling)
# ============================================================================

class BackgroundQueueWorker:
    """
    Background worker that polls Service Bus queue in a separate thread.

    This runs alongside the FastAPI HTTP server, allowing Azure Web App
    to receive health checks while processing queue messages.

    The worker uses CoreMachine.process_task_message() - identical to how
    Azure Functions process tasks. The only difference is the trigger
    mechanism (polling vs Function trigger).

    F7.18: Supports shared shutdown event for graceful shutdown coordination.
    When shutdown is signaled:
    - Stops accepting new messages
    - Allows in-flight task to complete (with checkpoint support)
    - Abandons queued messages for retry
    """

    def __init__(self, shutdown_event: Optional[threading.Event] = None):
        self._thread: Optional[threading.Thread] = None
        # Use shared shutdown event if provided, otherwise create own
        self._stop_event = shutdown_event if shutdown_event else threading.Event()
        self._uses_shared_event = shutdown_event is not None
        self._sb_client: Optional[ServiceBusClient] = None
        self._is_running = False
        self._messages_processed = 0
        self._last_poll_time: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._started_at: Optional[datetime] = None

        # Lazy-load config to avoid import issues at module load time
        self._config = None
        self._queue_name = None
        self._core_machine = None

        # Processing settings
        self.max_wait_time_seconds = 30  # Long poll
        self.poll_interval_on_error = 5  # Seconds to wait after error

    def _ensure_initialized(self):
        """Lazy initialization of config and CoreMachine."""
        if self._config is None:
            from config import get_config
            self._config = get_config()
            self._queue_name = self._config.queues.long_running_tasks_queue

        if self._core_machine is None:
            from core.machine import CoreMachine
            from jobs import ALL_JOBS
            from services import ALL_HANDLERS
            self._core_machine = CoreMachine(
                all_jobs=ALL_JOBS,
                all_handlers=ALL_HANDLERS
            )

    def _get_sb_client(self) -> ServiceBusClient:
        """
        Get or create Service Bus client.

        Authentication Priority (Identity-First):
            1. Managed Identity via SERVICE_BUS_FQDN (preferred, production)
            2. Connection string via ServiceBusConnection (local dev only)

        Required RBAC Roles (on Service Bus namespace):
            - Azure Service Bus Data Sender
            - Azure Service Bus Data Receiver
        """
        if self._sb_client is None:
            self._ensure_initialized()

            # PREFER Managed Identity (namespace) over connection string
            namespace = self._config.queues.namespace

            if namespace:
                # Production: Use Managed Identity (system-assigned)
                logger.info(f"[Queue Worker] Using Managed Identity for: {namespace}")
                credential = DefaultAzureCredential()
                self._sb_client = ServiceBusClient(
                    fully_qualified_namespace=namespace,
                    credential=credential
                )
            else:
                # Fallback: Connection string (local dev only)
                connection_string = self._config.queues.connection_string
                if not connection_string:
                    raise ValueError(
                        "No Service Bus connection configured. "
                        "Set SERVICE_BUS_FQDN (recommended) or ServiceBusConnection"
                    )
                logger.warning("[Queue Worker] Using connection string auth (use SERVICE_BUS_FQDN for production)")
                self._sb_client = ServiceBusClient.from_connection_string(connection_string)

        return self._sb_client

    def _process_message(
        self,
        message: ServiceBusReceivedMessage,
        receiver: ServiceBusReceiver
    ) -> bool:
        """Process a single message via CoreMachine with Docker context."""
        from core.schema.queue import TaskQueueMessage
        from core.docker_context import create_docker_context
        from infrastructure import RepositoryFactory

        start_time = time.time()
        task_id = "unknown"

        try:
            message_body = str(message)
            task_data = json.loads(message_body)
            task_message = TaskQueueMessage(**task_data)
            task_id = task_message.task_id

            logger.info("=" * 50)
            logger.info(f"[Queue] 📥 MESSAGE RECEIVED")
            logger.info(f"  Task ID: {task_id}")
            logger.info(f"  Task Type: {task_message.task_type}")
            logger.info(f"  Job ID: {task_message.parent_job_id}")
            logger.info(f"  Job Type: {task_message.job_type}")
            logger.info(f"  Stage: {task_message.stage}")
            logger.info("=" * 50)

            # Create Docker context with checkpoint, shutdown awareness, and pulse (F7.18, 22 JAN 2026)
            # Pulse is auto-started by create_docker_context() - updates last_pulse every 60s
            task_repo = RepositoryFactory.create_task_repository()
            docker_context = create_docker_context(
                task_id=task_message.task_id,
                job_id=task_message.parent_job_id,
                job_type=task_message.job_type,
                stage=task_message.stage,
                shutdown_event=self._stop_event,
                task_repo=task_repo,
                auto_start_pulse=True,  # Start pulse immediately
            )

            # Log checkpoint state if resuming
            if docker_context.checkpoint.current_phase > 0:
                logger.info(
                    f"[Queue] 🔄 RESUMING from checkpoint phase {docker_context.checkpoint.current_phase}"
                )

            logger.info(f"[Queue] ▶️ Starting task execution...")

            try:
                # Process via CoreMachine with Docker context
                result = self._core_machine.process_task_message(
                    task_message,
                    docker_context=docker_context
                )
            finally:
                # Always stop pulse when task processing ends (22 JAN 2026)
                docker_context.stop_pulse()

            elapsed = time.time() - start_time

            if result.get('success'):
                if result.get('interrupted'):
                    # Graceful shutdown - abandon message so another instance can resume
                    # Checkpoint was saved, delivery_count increments, message becomes visible
                    logger.warning("=" * 50)
                    logger.warning(f"[Queue] 🛑 TASK INTERRUPTED (graceful shutdown)")
                    logger.warning(f"  Task ID: {task_id[:16]}...")
                    logger.warning(f"  Phase completed: {result.get('phase_completed', '?')}")
                    logger.warning(f"  Elapsed: {elapsed:.2f}s")
                    logger.warning(f"  Pulses sent: {docker_context.pulse_count}")
                    logger.warning(f"  Action: ABANDONING message for resume by another instance")
                    logger.warning("=" * 50)
                    receiver.abandon_message(message)
                    return True  # Not an error, just interrupted
                else:
                    # Fully complete
                    logger.info("=" * 50)
                    logger.info(f"[Queue] ✅ TASK COMPLETED")
                    logger.info(f"  Task ID: {task_id[:16]}...")
                    logger.info(f"  Elapsed: {elapsed:.2f}s")
                    logger.info(f"  Pulses sent: {docker_context.pulse_count}")
                    logger.info(f"  Action: Message COMPLETED (removed from queue)")
                    logger.info("=" * 50)
                    receiver.complete_message(message)
                    self._messages_processed += 1

                    if result.get('stage_complete'):
                        logger.info(
                            f"[Queue] 🏁 Stage {task_message.stage} complete for job "
                            f"{task_message.parent_job_id[:16]}... - advancing to next stage"
                        )
                return True
            else:
                error = result.get('error', 'Unknown error')
                logger.error("=" * 50)
                logger.error(f"[Queue] ❌ TASK FAILED")
                logger.error(f"  Task ID: {task_id[:16]}...")
                logger.error(f"  Error: {error}")
                logger.error(f"  Elapsed: {elapsed:.2f}s")
                logger.error(f"  Pulses sent: {docker_context.pulse_count}")
                logger.error(f"  Action: Message DEAD-LETTERED")
                logger.error("=" * 50)
                receiver.dead_letter_message(
                    message,
                    reason="TaskFailed",
                    error_description=str(error)[:1024]
                )
                return False

        except json.JSONDecodeError as e:
            logger.error(f"[Queue] Invalid JSON: {e}")
            receiver.dead_letter_message(message, reason="JSONDecodeError", error_description=str(e))
            return False

        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(f"[Queue] Exception processing {task_id[:16]}... after {elapsed:.2f}s")
            try:
                receiver.abandon_message(message)
            except Exception:
                pass
            return False

    def _run_loop(self):
        """Main polling loop (runs in background thread)."""
        self._ensure_initialized()
        logger.info(f"[Queue Worker] Starting on queue: {self._queue_name}")
        self._is_running = True
        self._started_at = datetime.now(timezone.utc)

        try:
            client = self._get_sb_client()
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"[Queue Worker] Failed to connect: {e}")
            self._is_running = False
            return

        # Create AutoLockRenewer for long-running tasks (up to 2 hours)
        # This prevents competing consumers during lengthy COG processing
        # NOTE: We use MANUAL registration (not auto_lock_renewer param) for explicit control
        lock_renewer = AutoLockRenewer(max_lock_renewal_duration=7200)  # 2 hours in seconds
        logger.info("[Queue Worker] AutoLockRenewer initialized (max_duration=2h, manual registration)")

        logger.info("[Queue Worker] Entering main polling loop - waiting for messages...")

        while not self._stop_event.is_set():
            try:
                # Don't pass auto_lock_renewer to receiver - use manual registration instead
                # This provides explicit control over which messages get lock renewal
                logger.info(f"[Queue Worker] 🔄 Opening receiver for: {self._queue_name}")
                with client.get_queue_receiver(
                    queue_name=self._queue_name,
                    max_wait_time=self.max_wait_time_seconds,
                ) as receiver:
                    logger.info(f"[Queue Worker] ✅ Receiver opened, calling receive_messages()...")

                    self._last_poll_time = datetime.now(timezone.utc)
                    self._last_error = None

                    messages = receiver.receive_messages(
                        max_message_count=1,
                        max_wait_time=self.max_wait_time_seconds
                    )

                    logger.info(f"[Queue Worker] 📨 receive_messages() returned: {len(messages) if messages else 0} message(s)")

                    if not messages:
                        logger.info("[Queue Worker] ⏳ No messages in queue, will poll again...")
                        continue

                    for message in messages:
                        if self._stop_event.is_set():
                            logger.warning(
                                "[Queue Worker] 🛑 Shutdown detected BEFORE processing - "
                                "abandoning message for another instance"
                            )
                            receiver.abandon_message(message)
                            break

                        # MANUAL lock registration - register AFTER receiving, BEFORE processing
                        # This ensures lock renewal only for messages we're actually processing
                        lock_renewer.register(receiver, message, max_lock_renewal_duration=7200)
                        logger.info(f"[Queue Worker] 🔒 Lock registered for message (2h renewal)")

                        self._process_message(message, receiver)

            except (ServiceBusConnectionError, OperationTimeoutError) as e:
                self._last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"[Queue Worker] Transient error: {self._last_error}")
                if not self._stop_event.is_set():
                    self._stop_event.wait(self.poll_interval_on_error)

            except ServiceBusError as e:
                self._last_error = f"{type(e).__name__}: {e}"
                logger.error(f"[Queue Worker] Service Bus error: {self._last_error}")
                if not self._stop_event.is_set():
                    self._stop_event.wait(self.poll_interval_on_error)

            except Exception as e:
                self._last_error = f"{type(e).__name__}: {e}"
                logger.exception("[Queue Worker] Unexpected error")
                if not self._stop_event.is_set():
                    self._stop_event.wait(self.poll_interval_on_error)

        # Cleanup
        logger.info("[Queue Worker] 🛑 Exited polling loop - beginning cleanup")
        self._is_running = False

        try:
            lock_renewer.close()
            logger.info("[Queue Worker] Lock renewer closed")
        except Exception as e:
            logger.warning(f"[Queue Worker] Error closing lock renewer: {e}")

        if self._sb_client:
            try:
                self._sb_client.close()
                logger.info("[Queue Worker] Service Bus client closed")
            except Exception as e:
                logger.warning(f"[Queue Worker] Error closing Service Bus client: {e}")
            self._sb_client = None

        logger.info("=" * 60)
        logger.info("[Queue Worker] STOPPED")
        logger.info(f"  Messages processed this session: {self._messages_processed}")
        if self._started_at:
            uptime = (datetime.now(timezone.utc) - self._started_at).total_seconds()
            logger.info(f"  Uptime: {int(uptime // 3600)}h {int((uptime % 3600) // 60)}m {int(uptime % 60)}s")
        logger.info("=" * 60)

    def start(self):
        """Start the background worker thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[Queue Worker] Already running")
            return

        # Only clear event if we own it (not shared)
        if not self._uses_shared_event:
            self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[Queue Worker] Background thread started")

    def stop(self):
        """Stop the background worker thread."""
        logger.info("[Queue Worker] Stopping...")
        # Only set event if we own it (shared event is set by lifecycle)
        if not self._uses_shared_event:
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def get_status(self) -> dict:
        """Get current worker status."""
        return {
            "running": self._is_running,
            "queue_name": self._queue_name,
            "messages_processed": self._messages_processed,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_poll_time": self._last_poll_time.isoformat() if self._last_poll_time else None,
            "last_error": self._last_error,
            "uses_shared_shutdown": self._uses_shared_event,
            "shutdown_signaled": self._stop_event.is_set(),
        }


# Global instances with shared shutdown event (F7.18)
# Both workers use the same shutdown event from worker_lifecycle
# This enables coordinated graceful shutdown on SIGTERM
token_refresh_worker = TokenRefreshWorker(shutdown_event=worker_lifecycle.shutdown_event)
queue_worker = BackgroundQueueWorker(shutdown_event=worker_lifecycle.shutdown_event)


# ============================================================================
# CONNECTIVITY TESTS
# ============================================================================

def test_database_connectivity() -> dict:
    """
    Test database connectivity using current OAuth token.

    Returns:
        dict with success status and details
    """
    try:
        from infrastructure.auth import get_postgres_connection_string
        import psycopg

        conn_str = get_postgres_connection_string()

        with psycopg.connect(conn_str, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version(), current_database(), current_user")
                row = cur.fetchone()

                return {
                    "connected": True,
                    "version": row[0].split(",")[0] if row else None,
                    "database": row[1] if row else None,
                    "user": row[2] if row else None,
                }

    except Exception as e:
        logger.error(f"Database connectivity test failed: {e}")
        return {
            "connected": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


def test_storage_connectivity() -> dict:
    """
    Test storage connectivity using current OAuth token.

    Returns:
        dict with success status and details
    """
    try:
        from config import get_config
        from azure.storage.blob import BlobServiceClient
        from azure.identity import DefaultAzureCredential

        config = get_config()
        # Use silver zone account (primary storage for Docker worker)
        account_name = config.storage.silver.account_name

        if not account_name:
            return {
                "connected": False,
                "error": "AZURE_STORAGE_ACCOUNT_NAME not configured",
            }

        account_url = f"https://{account_name}.blob.core.windows.net"
        credential = DefaultAzureCredential()

        client = BlobServiceClient(account_url=account_url, credential=credential)

        # List containers (limited to 1) to verify connectivity
        container_pages = client.list_containers(results_per_page=1)
        first_page = next(container_pages.by_page(), [])
        containers = list(first_page)

        return {
            "connected": True,
            "account": account_name,
            "containers_accessible": len(containers) > 0,
        }

    except Exception as e:
        logger.error(f"Storage connectivity test failed: {e}")
        return {
            "connected": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# ============================================================================
# FASTAPI LIFESPAN
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan - initialize auth and start background workers."""
    from infrastructure.auth import initialize_docker_auth

    print("=" * 60, flush=True)
    print("DOCKER SERVICE - STARTING", flush=True)
    print("=" * 60, flush=True)

    # Register signal handlers for graceful shutdown (F7.18)
    worker_lifecycle.register_signal_handlers()

    # Initialize authentication (acquire tokens, configure GDAL)
    logger.info("Initializing Docker authentication...")
    auth_status = initialize_docker_auth()
    logger.info(f"Auth initialization: {auth_status}")

    # Start background token refresh
    token_refresh_worker.start()

    # Start background queue worker (polls long-running-tasks queue)
    queue_worker.start()

    yield

    # Shutdown (may have been initiated by SIGTERM via worker_lifecycle)
    print("DOCKER SERVICE - SHUTTING DOWN", flush=True)

    # Initiate shutdown if not already done (handles uvicorn shutdown)
    if not worker_lifecycle.is_shutting_down:
        worker_lifecycle.initiate_shutdown("lifespan_exit")

    # Wait for workers to finish (they will stop on their own via shared event)
    queue_worker.stop()
    token_refresh_worker.stop()

    print("DOCKER SERVICE - SHUTDOWN COMPLETE", flush=True)


# FastAPI app
app = FastAPI(
    title="Workers Entrance",
    description="Docker Container Health and Operations API",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# STATIC FILES AND TEMPLATES (23 JAN 2026 - UI Migration Phase 1)
# ============================================================================

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

# Mount static files (CSS, JS)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
    logger.info(f"Static files mounted from: {_static_dir}")
else:
    logger.warning(f"Static directory not found: {_static_dir}")


# ============================================================================
# UI ENDPOINTS (Jinja2 Templates)
# ============================================================================

from fastapi.responses import RedirectResponse


@app.get("/", response_class=RedirectResponse)
def root_redirect():
    """Redirect root to interface home."""
    return RedirectResponse(url="/interface/home", status_code=302)


@app.get("/interface/home", response_class=HTMLResponse)
def interface_home(request: Request):
    """
    UI Home Page - Landing page for Docker worker UI.

    Returns:
        HTML landing page with links to all UI sections
    """
    from templates_utils import render_template

    return render_template(
        request,
        "pages/admin/home.html",
        nav_active="/interface/home"
    )


@app.get("/interface/health", response_class=HTMLResponse)
def interface_health(request: Request):
    """
    UI Health Dashboard - System health monitoring page.

    Displays architecture diagram, component status, Docker worker resources,
    and database schema information. Loads health data asynchronously via JS.

    Returns:
        HTML health dashboard with auto-loading status
    """
    import os
    from templates_utils import render_template
    from config import get_config, get_app_mode_config

    # Build dynamic tooltips from config
    tooltips = {}
    docker_worker_url = ''

    try:
        config = get_config()
        app_mode_config = get_app_mode_config()
        docker_worker_url = app_mode_config.docker_worker_url or ''

        website_hostname = os.environ.get('WEBSITE_HOSTNAME', 'localhost')

        # Service Bus namespace
        service_bus_ns = config.queues.namespace or ''
        if not service_bus_ns:
            conn_str = config.queues.connection_string or ''
            if 'Endpoint=sb://' in conn_str:
                service_bus_ns = conn_str.split('Endpoint=sb://')[1].split('/')[0]

        # Database info
        db_host = config.database.host
        db_name = config.database.database
        app_schema = config.database.app_schema
        geo_schema = config.database.postgis_schema
        pgstac_schema = config.database.pgstac_schema

        # Storage accounts
        bronze_account = config.storage.bronze.account_name
        silver_account = config.storage.silver.account_name

        # Queue names
        jobs_queue = config.queues.jobs_queue
        long_queue = config.queues.long_running_tasks_queue
        docker_enabled = app_mode_config.docker_worker_enabled

        # TiTiler URL
        titiler_url = config.titiler_base_url.replace('https://', '').replace('http://', '')

        tooltips = {
            'comp-platform-api': f"{website_hostname}\nEndpoints: /api/platform/*, /api/jobs/*",
            'comp-orchestrator': f"{website_hostname}\nListens: {jobs_queue}",
            'comp-job-queues': f"{service_bus_ns}\nQueue: {jobs_queue}",
            'comp-job-tables': f"{db_host}\nDB: {db_name}\nSchema: {app_schema}.jobs",
            'comp-task-tables': f"{db_host}\nDB: {db_name}\nSchema: {app_schema}.tasks",
            'comp-output-tables': f"{db_host}\nDB: {db_name}\nSchemas: {geo_schema}, {pgstac_schema}",
            'comp-input-storage': f"{bronze_account}\nContainer: rasters",
            'comp-output-storage': f"{silver_account}\nContainer: cogs",
            'comp-titiler': f"{titiler_url}\nMode: {config.titiler_mode}",
            'comp-long-queue': f"{service_bus_ns}\nQueue: {long_queue}\nDocker: {'Enabled' if docker_enabled else 'Disabled'}",
            'comp-container': f"{docker_worker_url or 'Not configured'}\nQueue: {long_queue}",
        }
    except Exception as e:
        # Tooltips will be empty, but page will still render
        pass

    return render_template(
        request,
        "pages/admin/health.html",
        nav_active="/interface/health",
        tooltips=tooltips,
        docker_worker_url=docker_worker_url
    )


# ============================================================================
# HEALTH CHECK ENDPOINTS
# ============================================================================

@app.get("/livez")
def liveness_probe():
    """
    Kubernetes liveness probe.

    Returns 200 if the process is running.
    This should NEVER fail - if it does, Kubernetes restarts the container.

    Returns:
        Simple "ok" response
    """
    return {"status": "ok"}


@app.get("/readyz")
def readiness_probe():
    """
    Kubernetes readiness probe.

    Returns 200 if the container can serve traffic.
    Checks that we have valid tokens and can reach dependencies.

    Returns:
        Readiness status with component checks
    """
    from infrastructure.auth import get_token_status

    token_status = get_token_status()

    # Check if tokens are valid
    postgres_ready = token_status.get("postgres", {}).get("has_token", False)
    storage_ready = token_status.get("storage", {}).get("has_token", False)

    # Overall readiness
    ready = postgres_ready  # Storage is optional

    if not ready:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "postgres_token": postgres_ready,
                "storage_token": storage_ready,
            }
        )

    return {
        "status": "ready",
        "postgres_token": postgres_ready,
        "storage_token": storage_ready,
    }


@app.get("/health")
def health_check():
    """
    Detailed health check endpoint.

    Returns comprehensive health information including:
    - Hardware metrics (CPU, memory, platform)
    - Token status (TTL, expiry)
    - Database connectivity
    - Storage connectivity
    - Background worker status

    Returns:
        Detailed health status
    """
    import platform
    import psutil

    from infrastructure.auth import get_token_status
    from config import get_config

    config = get_config()

    # Get token status
    token_status = get_token_status()

    # Test connectivity
    db_status = test_database_connectivity()
    storage_status = test_storage_connectivity()

    # Hardware metrics (same format as Function App - 12 JAN 2026)
    memory = psutil.virtual_memory()
    process = psutil.Process()
    mem_info = process.memory_info()
    total_ram_gb = round(memory.total / (1024**3), 1)

    hardware = {
        "cpu_count": psutil.cpu_count(),
        "total_ram_gb": total_ram_gb,
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "azure_site_name": os.environ.get("WEBSITE_SITE_NAME", "docker-worker"),
        "azure_sku": os.environ.get("WEBSITE_SKU", "Container"),
    }

    # Instance info for log correlation (matches Function App pattern)
    instance = {
        "container_id": os.environ.get("HOSTNAME", "unknown")[:12],
        "website_instance_id": os.environ.get("WEBSITE_INSTANCE_ID", "local")[:8],
        "app_name": os.environ.get("APP_NAME", "docker-worker"),
    }

    # Process info
    try:
        create_time = datetime.fromtimestamp(process.create_time(), tz=timezone.utc)
        uptime_seconds = (datetime.now(timezone.utc) - create_time).total_seconds()
    except Exception:
        uptime_seconds = 0

    process_info = {
        "pid": process.pid,
        "uptime_seconds": round(uptime_seconds),
        "uptime_human": f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m",
        "threads": process.num_threads(),
    }

    # Memory stats (system and process)
    memory_stats = {
        "system_total_gb": total_ram_gb,
        "system_available_mb": round(memory.available / (1024**2), 1),
        "system_percent": round(memory.percent, 1),
        "process_rss_mb": round(mem_info.rss / (1024**2), 1),
        "process_vms_mb": round(mem_info.vms / (1024**2), 1),
        "process_percent": round(process.memory_percent(), 2),
        "cpu_percent": round(psutil.cpu_percent(interval=0.1), 1),
    }

    # Capacity thresholds (same as Function App)
    capacity = {
        "safe_file_limit_mb": round((total_ram_gb * 1024) / 4, 0),
        "warning_threshold_percent": 80,
        "critical_threshold_percent": 90,
    }

    # Overall health - unhealthy if DB down or shutdown in progress
    healthy = db_status.get("connected", False) and not worker_lifecycle.is_shutting_down

    # Connection pool stats (F7.18)
    try:
        from infrastructure.connection_pool import ConnectionPoolManager
        pool_stats = ConnectionPoolManager.get_pool_stats()
    except Exception as e:
        pool_stats = {"error": str(e)}

    # Determine status string
    if worker_lifecycle.is_shutting_down:
        status = "shutting_down"
    elif healthy:
        status = "healthy"
    else:
        status = "unhealthy"

    response = {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        # Lifecycle status (F7.18 - graceful shutdown)
        "lifecycle": worker_lifecycle.get_status(),
        # Runtime environment (matches Function App pattern)
        "runtime": {
            "hardware": hardware,
            "instance": instance,
            "process": process_info,
            "memory": memory_stats,
            "capacity": capacity,
        },
        "config": {
            "database_host": config.database.host,
            "storage_account": config.storage.silver.account_name,
            "managed_identity": config.database.use_managed_identity,
            "service_bus_fqdn": config.queues.namespace,
        },
        "tokens": token_status,
        "connectivity": {
            "database": db_status,
            "storage": storage_status,
        },
        "background_workers": {
            "token_refresh": token_refresh_worker.get_status(),
            "queue_worker": queue_worker.get_status(),
        },
        # Connection pool stats (F7.18)
        "connection_pool": pool_stats,
    }

    # Return 503 if unhealthy OR shutting down (prevents new traffic during shutdown)
    if not healthy or worker_lifecycle.is_shutting_down:
        return JSONResponse(status_code=503, content=response)

    return response


# ============================================================================
# DIAGNOSTIC ENDPOINTS
# ============================================================================

@app.get("/auth/status")
def auth_status():
    """Get detailed authentication status."""
    from infrastructure.auth import get_token_status

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tokens": get_token_status(),
        "refresh_worker": token_refresh_worker.get_status(),
    }


@app.post("/auth/refresh")
def force_token_refresh():
    """Force immediate token refresh."""
    from infrastructure.auth import refresh_all_tokens

    logger.info("Manual token refresh requested")
    status = refresh_all_tokens()

    return {
        "status": "refreshed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": status,
    }


@app.get("/test/database")
def test_database():
    """Test database connectivity."""
    return test_database_connectivity()


@app.get("/test/storage")
def test_storage():
    """Test storage connectivity."""
    return test_storage_connectivity()


@app.get("/queue/status")
def get_queue_status():
    """
    Get detailed queue worker status.

    Returns:
        Queue worker status including messages processed, last poll time, errors
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "worker": queue_worker.get_status(),
    }


# ============================================================================
# LOGGING HEALTH CHECK (21 JAN 2026)
# ============================================================================

@app.get("/test/logging")
def test_logging():
    """
    Test that logging to Application Insights is working.

    This endpoint:
    1. Checks if APPLICATIONINSIGHTS_CONNECTION_STRING is set
    2. Verifies Azure Monitor OpenTelemetry was configured
    3. Emits a test log message at INFO level
    4. Returns diagnostic information

    Use this to verify logs will appear in Application Insights.

    Returns:
        Logging configuration status and test message ID
    """
    import uuid

    test_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now(timezone.utc).isoformat()

    # Check configuration
    conn_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    app_name = os.environ.get("APP_NAME", "unknown")
    environment = os.environ.get("ENVIRONMENT", "unknown")

    # Parse instrumentation key from connection string
    instrumentation_key = None
    app_id = None
    if conn_string:
        for part in conn_string.split(";"):
            if part.startswith("InstrumentationKey="):
                instrumentation_key = part.split("=", 1)[1]
            elif part.startswith("ApplicationId="):
                app_id = part.split("=", 1)[1]

    status = {
        "timestamp": timestamp,
        "test_id": test_id,
        "configuration": {
            "connection_string_set": bool(conn_string),
            "instrumentation_key": instrumentation_key[:12] + "..." if instrumentation_key else None,
            "application_id": app_id,
            "azure_monitor_enabled": _azure_monitor_enabled,
            "app_name": app_name,
            "environment": environment,
            "observability_mode": os.environ.get("OBSERVABILITY_MODE", "not set"),
        },
        "expected_behavior": {
            "logs_visible_in": f"Application Insights → Logs → traces",
            "query_hint": f"traces | where message contains 'LOGGING_TEST_{test_id}'",
            "delay_note": "Logs may take 1-3 minutes to appear in App Insights",
        }
    }

    if conn_string and _azure_monitor_enabled:
        # Emit test log message - this should appear in Application Insights
        logger.info(
            f"LOGGING_TEST_{test_id} - Test log message from Docker worker health check",
            extra={
                "custom_dimensions": {
                    "test_id": test_id,
                    "test_type": "logging_health_check",
                    "app_name": app_name,
                    "environment": environment,
                }
            }
        )
        status["result"] = "success"
        status["message"] = f"Test log emitted. Search for 'LOGGING_TEST_{test_id}' in App Insights."
    elif not conn_string:
        status["result"] = "error"
        status["message"] = "APPLICATIONINSIGHTS_CONNECTION_STRING not set"
    else:
        status["result"] = "warning"
        status["message"] = "Azure Monitor OpenTelemetry not enabled (check startup logs)"

    return status


@app.post("/test/logging/verify")
def verify_logging():
    """
    Emit multiple test log messages at different levels for verification.

    This endpoint logs at DEBUG, INFO, WARNING, and ERROR levels,
    then provides Application Insights queries to find them.

    Returns:
        Test IDs and queries for verification
    """
    import uuid

    batch_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now(timezone.utc).isoformat()

    # Log at different levels
    test_messages = []

    # INFO level
    info_msg = f"LOGGING_VERIFY_{batch_id}_INFO"
    logger.info(info_msg, extra={"custom_dimensions": {"batch_id": batch_id, "level": "INFO"}})
    test_messages.append({"level": "INFO", "message": info_msg})

    # WARNING level
    warn_msg = f"LOGGING_VERIFY_{batch_id}_WARNING"
    logger.warning(warn_msg, extra={"custom_dimensions": {"batch_id": batch_id, "level": "WARNING"}})
    test_messages.append({"level": "WARNING", "message": warn_msg})

    # ERROR level
    error_msg = f"LOGGING_VERIFY_{batch_id}_ERROR"
    logger.error(error_msg, extra={"custom_dimensions": {"batch_id": batch_id, "level": "ERROR"}})
    test_messages.append({"level": "ERROR", "message": error_msg})

    return {
        "timestamp": timestamp,
        "batch_id": batch_id,
        "messages_logged": test_messages,
        "verification": {
            "app_insights_query": f"traces | where message contains 'LOGGING_VERIFY_{batch_id}' | order by timestamp desc",
            "expected_count": 3,
            "delay_note": "Wait 1-3 minutes, then run the query in Application Insights → Logs",
        }
    }


# ============================================================================
# HANDLER ENDPOINTS (for future use)
# ============================================================================

@app.get("/handlers")
def list_handlers():
    """List available handlers."""
    try:
        from services import ALL_HANDLERS
        return {
            "count": len(ALL_HANDLERS),
            "handlers": sorted(ALL_HANDLERS.keys())
        }
    except Exception as e:
        return {"count": 0, "error": str(e)}


@app.get("/jobs")
def list_jobs():
    """List available job types."""
    try:
        from jobs import ALL_JOBS
        return {
            "count": len(ALL_JOBS),
            "jobs": sorted(ALL_JOBS.keys())
        }
    except Exception as e:
        return {"count": 0, "error": str(e)}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "80"))

    logger.info("=" * 60)
    logger.info("Docker Service - HTTP API + Queue Worker")
    logger.info(f"Port: {port}")
    logger.info("=" * 60)
    logger.info("Health Endpoints:")
    logger.info("  GET  /livez        - Liveness probe")
    logger.info("  GET  /readyz       - Readiness probe")
    logger.info("  GET  /health       - Detailed health check")
    logger.info("  GET  /queue/status - Queue worker status")
    logger.info("Auth Endpoints:")
    logger.info("  GET  /auth/status  - Token status")
    logger.info("  POST /auth/refresh - Force token refresh")
    logger.info("Test Endpoints:")
    logger.info("  GET  /test/database - Test DB connectivity")
    logger.info("  GET  /test/storage  - Test storage connectivity")
    logger.info("=" * 60)
    logger.info("Background Workers:")
    logger.info("  - Token refresh (every 45 min)")
    logger.info("  - Queue polling (long-running-tasks)")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=port)
