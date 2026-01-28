#!/usr/bin/env python3
# ============================================================================
# CLAUDE CONTEXT - DOCKER SERVICE (HTTP + Queue Worker)
# ============================================================================
# STATUS: Core Component - Docker container with HTTP API and queue processing
# PURPOSE: Health checks + Service Bus queue polling for container-tasks (V0.8)
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
    - Queue polling thread (polls container-tasks queue)

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
            self._queue_name = self._config.queues.container_tasks_queue

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

            # Create Docker context with checkpoint, shutdown awareness, pulse, and memory watchdog
            # (F7.18, 22 JAN 2026; Memory watchdog added 24 JAN 2026)
            # - Pulse: updates last_pulse every 60s for liveness tracking
            # - Memory watchdog: triggers graceful shutdown before OOM kill (80% threshold)
            task_repo = RepositoryFactory.create_task_repository()
            docker_context = create_docker_context(
                task_id=task_message.task_id,
                job_id=task_message.parent_job_id,
                job_type=task_message.job_type,
                stage=task_message.stage,
                shutdown_event=self._stop_event,
                task_repo=task_repo,
                auto_start_pulse=True,           # Start pulse immediately
                enable_memory_watchdog=True,     # Prevent OOM kills (24 JAN 2026)
                memory_threshold_percent=80,     # Trigger shutdown at 80% memory usage
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
                # Always stop pulse and memory watchdog when task processing ends
                # (22 JAN 2026 - pulse; 24 JAN 2026 - memory watchdog)
                docker_context.stop_pulse()
                docker_context.stop_memory_watchdog()

            elapsed = time.time() - start_time

            if result.get('success'):
                if result.get('interrupted'):
                    # Graceful shutdown - abandon message so another instance can resume
                    # Checkpoint was saved, delivery_count increments, message becomes visible
                    oom_abort = docker_context.oom_abort_requested
                    reason = "MEMORY PRESSURE (OOM prevention)" if oom_abort else "graceful shutdown"
                    emoji = "🧠🛑" if oom_abort else "🛑"

                    logger.warning("=" * 50)
                    logger.warning(f"[Queue] {emoji} TASK INTERRUPTED ({reason})")
                    logger.warning(f"  Task ID: {task_id[:16]}...")
                    logger.warning(f"  Phase completed: {result.get('phase_completed', '?')}")
                    logger.warning(f"  Elapsed: {elapsed:.2f}s")
                    logger.warning(f"  Pulses sent: {docker_context.pulse_count}")

                    # Log memory stats if available (24 JAN 2026)
                    mem_stats = docker_context.memory_watchdog_stats
                    if mem_stats:
                        logger.warning(
                            f"  Memory: peak={mem_stats['peak_gb']:.2f}GB / "
                            f"limit={mem_stats['limit_gb']:.1f}GB "
                            f"({mem_stats['peak_gb']/mem_stats['limit_gb']*100:.1f}%)"
                        )

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

                    # Log memory stats if available (24 JAN 2026)
                    mem_stats = docker_context.memory_watchdog_stats
                    if mem_stats:
                        logger.info(
                            f"  Memory: peak={mem_stats['peak_gb']:.2f}GB / "
                            f"limit={mem_stats['limit_gb']:.1f}GB "
                            f"({mem_stats['peak_gb']/mem_stats['limit_gb']*100:.1f}%)"
                        )

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
        #
        # Lock Renewal Logging (25 JAN 2026):
        # - on_lock_renew_failure callback logs when renewal fails
        # - Failure usually means message was already completed/abandoned or network issue
        lock_renewal_count = [0]  # Mutable counter for closure

        def on_lock_renew_failure(
            renewable: ServiceBusReceivedMessage,
            error: Exception
        ) -> None:
            """Callback when lock renewal fails."""
            lock_renewal_count[0] += 1
            logger.error(
                f"🔒❌ LOCK RENEWAL FAILED (attempt #{lock_renewal_count[0]}): {error}"
            )
            # Log message details if available
            try:
                logger.error(f"   Message ID: {renewable.message_id}")
                logger.error(f"   Lock expiry was: {renewable.locked_until_utc}")
            except Exception:
                pass

        lock_renewer = AutoLockRenewer(
            max_lock_renewal_duration=7200,  # 2 hours in seconds
            on_lock_renew_failure=on_lock_renew_failure
        )
        logger.info("[Queue Worker] AutoLockRenewer initialized (max_duration=2h, manual registration, with failure callback)")

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

                        # Detailed lock logging (25 JAN 2026)
                        try:
                            initial_lock_until = message.locked_until_utc
                            message_id = message.message_id
                            logger.info(f"[Queue Worker] 🔒 Lock registered for message")
                            logger.info(f"   Message ID: {message_id}")
                            logger.info(f"   Initial lock until: {initial_lock_until}")
                            logger.info(f"   Auto-renewal: up to 2 hours")
                            logger.info(f"   Lock renewal interval: ~5 mins (Azure SDK default)")
                        except Exception as e:
                            logger.info(f"[Queue Worker] 🔒 Lock registered for message (2h renewal)")
                            logger.debug(f"   Could not get lock details: {e}")

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
# ETL MOUNT VALIDATION (24 JAN 2026)
# ============================================================================

def validate_etl_mount() -> Dict[str, Any]:
    """
    Validate ETL mount at startup when RASTER_USE_ETL_MOUNT=true.

    Checks:
    1. Mount path exists
    2. Mount is writable
    3. GDAL can use mount for temp files (CPL_TMPDIR)

    Returns:
        Dict with validation status and details

    Raises:
        RuntimeError: If mount is enabled but validation fails (fatal)
    """
    import shutil

    from config import get_config
    config = get_config()
    raster_config = config.raster

    result = {
        "mount_enabled": raster_config.use_etl_mount,
        "mount_path": raster_config.etl_mount_path,
        "validated": False,
        "error": None,
    }

    if not raster_config.use_etl_mount:
        # V0.8: Mount is expected - warn if disabled
        result["message"] = "ETL mount disabled - DEGRADED STATE"
        result["degraded"] = True
        logger.warning("=" * 60)
        logger.warning("⚠️ V0.8 WARNING: ETL MOUNT IS DISABLED")
        logger.warning("=" * 60)
        logger.warning("  RASTER_USE_ETL_MOUNT=false")
        logger.warning("  This is a DEGRADED state - mount is expected in production")
        logger.warning("  Large raster processing may fail due to temp space limits")
        logger.warning("  Set RASTER_USE_ETL_MOUNT=true and configure Azure Files mount")
        logger.warning("=" * 60)
        return result

    mount_path = raster_config.etl_mount_path
    logger.info(f"📁 ETL Mount: Validating {mount_path}...")

    # Check 1: Mount exists
    if not os.path.exists(mount_path):
        error_msg = f"ETL mount path does not exist: {mount_path}"
        logger.error(f"❌ {error_msg}")
        result["error"] = error_msg
        raise RuntimeError(f"STARTUP FAILED: {error_msg}")

    if not os.path.isdir(mount_path):
        error_msg = f"ETL mount path is not a directory: {mount_path}"
        logger.error(f"❌ {error_msg}")
        result["error"] = error_msg
        raise RuntimeError(f"STARTUP FAILED: {error_msg}")

    result["exists"] = True
    logger.info(f"  ✓ Mount path exists")

    # Check 2: Mount is writable
    test_file = f"{mount_path}/.startup-test-{os.getpid()}"
    try:
        with open(test_file, "w") as f:
            f.write(f"startup validation {datetime.now(timezone.utc).isoformat()}")
        os.remove(test_file)
        result["writable"] = True
        logger.info(f"  ✓ Mount is writable")
    except Exception as e:
        error_msg = f"ETL mount not writable: {e}"
        logger.error(f"❌ {error_msg}")
        result["error"] = error_msg
        raise RuntimeError(f"STARTUP FAILED: {error_msg}")

    # Check 3: Disk space
    try:
        usage = shutil.disk_usage(mount_path)
        free_gb = usage.free / (1024 ** 3)
        result["disk_space"] = {
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "free_gb": round(free_gb, 1),
            "percent_free": round((usage.free / usage.total) * 100, 1),
        }
        logger.info(f"  ✓ Disk space: {free_gb:.1f} GB free")

        # Warn if low space
        if free_gb < 50:
            logger.warning(f"  ⚠️ Low disk space on ETL mount: {free_gb:.1f} GB")
            result["warning"] = f"Low disk space: {free_gb:.1f} GB"
    except Exception as e:
        logger.warning(f"  ⚠️ Could not check disk space: {e}")
        result["disk_space_error"] = str(e)

    # Check 4: Configure GDAL CPL_TMPDIR
    try:
        from osgeo import gdal
        os.environ["CPL_TMPDIR"] = mount_path
        gdal.SetConfigOption("CPL_TMPDIR", mount_path)
        result["cpl_tmpdir_configured"] = True
        logger.info(f"  ✓ GDAL CPL_TMPDIR configured: {mount_path}")
    except Exception as e:
        error_msg = f"Failed to configure GDAL CPL_TMPDIR: {e}"
        logger.error(f"❌ {error_msg}")
        result["error"] = error_msg
        raise RuntimeError(f"STARTUP FAILED: {error_msg}")

    result["validated"] = True
    result["message"] = "ETL mount validated successfully"
    logger.info(f"✅ ETL Mount: VALIDATED and ENABLED")
    logger.info(f"   Mount path: {mount_path}")
    logger.info(f"   All raster temp files will use this mount")
    logger.info(f"   in_memory will be forced to False for disk-based processing")

    return result


# Global mount validation status (populated at startup)
_etl_mount_status: Optional[Dict[str, Any]] = None


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

    # Validate ETL mount if enabled (24 JAN 2026)
    # This will raise RuntimeError if mount is enabled but validation fails
    global _etl_mount_status
    try:
        _etl_mount_status = validate_etl_mount()
    except RuntimeError as e:
        logger.critical(f"🚨 {e}")
        print(f"STARTUP FAILED: {e}", flush=True)
        raise

    # Start background token refresh
    token_refresh_worker.start()

    # Start background queue worker (polls container-tasks queue)
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

        # Queue names (V0.8)
        jobs_queue = config.queues.jobs_queue
        container_queue = config.queues.container_tasks_queue
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
            'comp-container-queue': f"{service_bus_ns}\nQueue: {container_queue}\nDocker: {'Enabled' if docker_enabled else 'Disabled'}",
            'comp-container': f"{docker_worker_url or 'Not configured'}\nQueue: {container_queue}",
        }
    except Exception as e:
        # Tooltips will be empty, but page will still render
        pass

    # Get Function App URL for cross-system health (GAP-01)
    function_app_url = ''
    try:
        function_app_url = config.platform.etl_app_base_url or ''
        if function_app_url and not function_app_url.startswith('http'):
            function_app_url = f'https://{function_app_url}'
    except Exception:
        pass

    return render_template(
        request,
        "pages/admin/health.html",
        nav_active="/interface/health",
        tooltips=tooltips,
        docker_worker_url=docker_worker_url,
        function_app_url=function_app_url
    )


@app.get("/interface/collections", response_class=HTMLResponse)
def interface_collections(request: Request):
    """
    UI Collections Browser - Unified STAC + OGC collections.

    Displays all collections from both STAC (raster) and OGC Features (vector)
    APIs in a unified browsing interface with filtering and search.

    Returns:
        HTML collections browser
    """
    from templates_utils import render_template
    from config import get_config

    # Get API URLs for JavaScript
    stac_api_url = '/api/stac'
    ogc_api_url = '/api/features'
    tipg_url = ''
    titiler_url = ''

    try:
        config = get_config()
        # TiPG URL for vector tiles/map
        tipg_url = getattr(config, 'tipg_base_url', '') or ''
        # TiTiler URL for raster tiles/map
        titiler_url = config.titiler_base_url or ''
    except Exception:
        pass

    return render_template(
        request,
        "pages/browse/collections.html",
        nav_active="/interface/collections",
        stac_api_url=stac_api_url,
        ogc_api_url=ogc_api_url,
        tipg_url=tipg_url,
        titiler_url=titiler_url
    )


# ============================================================================
# SUBMIT INTERFACE (Unified Raster + Vector Submission)
# ============================================================================

@app.get("/interface/submit", response_class=HTMLResponse)
def interface_submit(request: Request):
    """
    Unified Data Submission Interface.

    Combines raster and vector submission with:
    - File source selection (browse storage or upload)
    - Automatic file type detection
    - Type-specific form fields (CSV geometry, raster options)
    - cURL preview for Platform API

    Returns:
        HTML submission form
    """
    from templates_utils import render_template

    return render_template(
        request,
        "pages/submit/unified.html",
        nav_active="/interface/submit",
        api_base_url="/api",
        platform_api_url="/api/platform"
    )


@app.get("/interface/submit/partial/browser", response_class=HTMLResponse)
def interface_submit_browser_partial(request: Request):
    """HTMX partial for file browser."""
    from templates_utils import render_fragment

    return render_fragment(
        request,
        "pages/submit/_file_browser.html"
    )


@app.get("/interface/submit/partial/upload", response_class=HTMLResponse)
def interface_submit_upload_partial(request: Request):
    """HTMX partial for file upload."""
    from templates_utils import render_fragment

    return render_fragment(
        request,
        "pages/submit/_file_upload.html"
    )


@app.get("/interface/submit/partial/containers", response_class=HTMLResponse)
def interface_submit_containers(request: Request, zone: str = "bronze"):
    """
    HTMX partial for container dropdown options.

    Args:
        zone: Storage zone (default: bronze)

    Returns:
        HTML option elements for containers
    """
    from infrastructure.blob import BlobRepository

    try:
        repo = BlobRepository.for_zone(zone)
        containers = repo.list_containers()

        if not containers:
            return '<option value="">No containers in zone</option>'

        options = ['<option value="">Select container...</option>']
        for c in containers:
            options.append(f'<option value="{c["name"]}">{c["name"]}</option>')

        return '\n'.join(options)

    except Exception as e:
        return f'<option value="">Error: {str(e)[:50]}</option>'


@app.get("/interface/submit/partial/files", response_class=HTMLResponse)
def interface_submit_files(
    request: Request,
    zone: str = "bronze",
    container: str = "",
    prefix: str = "",
    limit: int = 250
):
    """
    HTMX partial for file table rows.

    Filters for supported geospatial extensions (raster + vector).

    Args:
        zone: Storage zone
        container: Container name
        prefix: Path prefix filter
        limit: Maximum files to return

    Returns:
        HTML table rows for matching files
    """
    from infrastructure.blob import BlobRepository
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Supported extensions
    EXTENSIONS = [
        '.tif', '.tiff', '.geotiff', '.img', '.jp2', '.ecw', '.vrt', '.nc', '.hdf', '.hdf5',
        '.csv', '.geojson', '.json', '.gpkg', '.kml', '.kmz', '.shp', '.zip'
    ]

    RASTER_EXTENSIONS = ['.tif', '.tiff', '.geotiff', '.img', '.jp2', '.ecw', '.vrt', '.nc', '.hdf', '.hdf5']

    if not container:
        return '<tr><td colspan="4" class="empty-state">Please select a container</td></tr>'

    try:
        repo = BlobRepository.for_zone(zone)
        blobs = repo.list_blobs(
            container=container,
            prefix=prefix if prefix else "",
            limit=limit * 2
        )

        # Filter for supported extensions
        filtered = []
        for blob in blobs:
            name = blob.get('name', '').lower()
            if any(name.endswith(ext) for ext in EXTENSIONS):
                filtered.append(blob)
            if len(filtered) >= limit:
                break

        if not filtered:
            return '''
            <tr>
                <td colspan="4">
                    <div class="empty-state" style="margin: 20px 0;">
                        <h3>No Supported Files Found</h3>
                        <p>No files with supported geospatial extensions in this location.</p>
                    </div>
                </td>
            </tr>
            '''

        # Build table rows
        rows = []
        eastern = ZoneInfo('America/New_York')

        for blob in filtered:
            size_mb = blob.get('size', 0) / (1024 * 1024)
            name = blob.get('name', '')
            short_name = name.split('/')[-1] if '/' in name else name

            # Format date
            last_modified = blob.get('last_modified', '')
            date_str = 'N/A'
            if last_modified:
                try:
                    dt = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                    dt_eastern = dt.astimezone(eastern)
                    date_str = dt_eastern.strftime('%m/%d/%Y')
                except Exception:
                    pass

            # Get extension and type
            ext = short_name.split('.')[-1].lower() if '.' in short_name else ''
            is_raster = f'.{ext}' in RASTER_EXTENSIONS
            type_class = 'file-type-raster' if is_raster else 'file-type-vector'

            # Size class (warning for >1GB)
            size_class = 'file-size warning' if size_mb > 1024 else 'file-size'

            rows.append(f'''
            <tr class="file-row"
                onclick="selectFile('{name}', '{container}', '{zone}', {size_mb:.2f})"
                data-blob="{name}"
                data-container="{container}"
                data-zone="{zone}"
                data-size="{size_mb:.2f}">
                <td><div class="file-name" title="{name}">{short_name}</div></td>
                <td><span class="{size_class}">{size_mb:.2f} MB</span></td>
                <td><span class="file-date">{date_str}</span></td>
                <td><span class="file-type-badge {type_class}">{ext.upper()}</span></td>
            </tr>''')

        # Show table, hide initial state via OOB swap
        table_trigger = '<div id="files-initial-state" hx-swap-oob="true" class="empty-state hidden"></div>'

        return '\n'.join(rows) + table_trigger

    except Exception as e:
        return f'''
        <tr>
            <td colspan="4">
                <div class="empty-state" style="margin: 20px 0;">
                    <h3>Error Loading Files</h3>
                    <p>{str(e)[:100]}</p>
                </div>
            </td>
        </tr>
        '''


@app.post("/interface/submit/upload")
async def interface_submit_upload_handler(request: Request):
    """
    Handle file upload to blob storage.

    Returns:
        JSON with blob reference on success
    """
    from fastapi.responses import JSONResponse
    from infrastructure.blob import BlobRepository

    try:
        form = await request.form()
        file = form.get('file')
        container = form.get('container')
        path = form.get('path', '')

        if not file or not container:
            return JSONResponse(
                {"error": "File and container required"},
                status_code=400
            )

        # Read file content
        content = await file.read()

        # Determine blob path
        blob_name = path if path else file.filename

        # Upload to bronze storage
        repo = BlobRepository.for_zone('bronze')
        repo.upload_blob(
            container=container,
            blob_name=blob_name,
            data=content,
            content_type=file.content_type or 'application/octet-stream'
        )

        return JSONResponse({
            "success": True,
            "blob_name": blob_name,
            "container": container,
            "size": len(content)
        })

    except Exception as e:
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


@app.post("/interface/submit/process", response_class=HTMLResponse)
async def interface_submit_process(request: Request):
    """
    Handle form submission - calls Platform API.

    Returns:
        HTML result fragment
    """
    import httpx

    try:
        form = await request.form()
        form_dict = dict(form)

        # Determine API endpoint based on data type
        data_type = form_dict.get('data_type', 'vector')
        endpoint = '/api/platform/raster' if data_type == 'raster' else '/api/platform/vector'

        # Build request body
        body = {
            'dataset_id': form_dict.get('dataset_id'),
            'resource_id': form_dict.get('resource_id'),
            'version_id': form_dict.get('version_id', 'v1.0'),
            'blob_name': form_dict.get('blob_name'),
            'container_name': form_dict.get('container_name'),
        }

        # Add optional fields
        # Support both 'title' (new) and 'service_name' (legacy) for backward compatibility
        if form_dict.get('title'):
            body['title'] = form_dict['title']
        elif form_dict.get('service_name'):
            body['title'] = form_dict['service_name']
        if form_dict.get('description'):
            body['description'] = form_dict['description']
        if form_dict.get('access_level'):
            body['access_level'] = form_dict['access_level']
        if form_dict.get('tags'):
            body['tags'] = [t.strip() for t in form_dict['tags'].split(',')]
        if form_dict.get('overwrite'):
            body['overwrite'] = True

        # Raster-specific
        if data_type == 'raster':
            if form_dict.get('raster_type') and form_dict['raster_type'] != 'auto':
                body['raster_type'] = form_dict['raster_type']
            if form_dict.get('output_tier'):
                body['output_tier'] = form_dict['output_tier']
            if form_dict.get('input_crs'):
                body['input_crs'] = form_dict['input_crs']
            if form_dict.get('raster_collection_id'):
                body['collection_id'] = form_dict['raster_collection_id']
            if form_dict.get('use_docker'):
                body['processing_mode'] = 'docker'

        # Vector CSV-specific
        if form_dict.get('file_extension') == 'csv':
            if form_dict.get('lat_column'):
                body['lat_column'] = form_dict['lat_column']
            if form_dict.get('lon_column'):
                body['lon_column'] = form_dict['lon_column']
            if form_dict.get('wkt_column'):
                body['wkt_column'] = form_dict['wkt_column']

        # Make request to Platform API
        base_url = str(request.base_url).rstrip('/')
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}{endpoint}",
                json=body,
                timeout=60.0
            )

        if response.status_code in [200, 202]:
            result = response.json()
            job_id = result.get('job_id', 'unknown')
            return f'''
            <div class="submit-result success">
                <h3>Job Submitted Successfully</h3>
                <p><strong>Job ID:</strong> {job_id}</p>
                <p>View job status at: <a href="/interface/jobs/{job_id}">/interface/jobs/{job_id}</a></p>
            </div>
            '''
        else:
            error = response.text[:200]
            return f'''
            <div class="submit-result error">
                <h3>Submission Failed</h3>
                <p>Status: {response.status_code}</p>
                <p>{error}</p>
            </div>
            '''

    except Exception as e:
        return f'''
        <div class="submit-result error">
            <h3>Error</h3>
            <p>{str(e)[:200]}</p>
        </div>
        '''


# ============================================================================
# JOB MONITOR INTERFACE (25 JAN 2026 - Job List and Detail)
# ============================================================================

from templates_utils import templates
from config import __version__

@app.get("/interface/jobs", response_class=HTMLResponse)
async def interface_jobs_list(
    request: Request,
    status: str = None,
    hours: int = 24
):
    """
    Job list page showing recent jobs with status and event counts.

    Query params:
        status: Filter by status (processing, completed, failed)
        hours: Time range in hours (default 24)
    """
    try:
        from infrastructure import JobRepository, JobEventRepository
        from core.models import JobStatus
        from datetime import datetime, timezone, timedelta

        job_repo = JobRepository()
        event_repo = JobEventRepository()

        # Calculate time cutoff
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Get jobs with optional status filter
        status_filter = None
        if status:
            try:
                status_filter = JobStatus(status.upper())
            except ValueError:
                pass  # Invalid status, ignore filter

        all_jobs = job_repo.list_jobs(status_filter=status_filter)

        # Filter by time and limit
        # Handle both timezone-aware and timezone-naive datetimes
        def job_in_range(job):
            if not job.created_at:
                return False
            job_time = job.created_at
            # Make timezone-aware if naive
            if job_time.tzinfo is None:
                job_time = job_time.replace(tzinfo=timezone.utc)
            return job_time >= cutoff

        filtered_jobs = [j for j in all_jobs if job_in_range(j)][:100]

        # Calculate stats
        stats = {
            'total': len(filtered_jobs),
            'processing': sum(1 for j in filtered_jobs if j.status and j.status.value.lower() == 'processing'),
            'completed': sum(1 for j in filtered_jobs if j.status and j.status.value.lower() == 'completed'),
            'failed': sum(1 for j in filtered_jobs if j.status and j.status.value.lower() in ('failed', 'completed_with_errors'))
        }

        # Convert to enriched dictionaries for template
        jobs = []
        for job in filtered_jobs:
            status_val = job.status.value.lower() if job.status else 'unknown'
            job_dict = {
                'job_id': job.job_id,
                'job_type': job.job_type,
                'status': status_val,
                'current_stage': job.stage,
                'total_stages': job.total_stages,
                'parameters': job.parameters,
                'created_at': job.created_at,
                'completed_at': job.updated_at if status_val == 'completed' else None,
                'event_count': 0,
                'has_failure': False,
                'latest_event': None
            }

            # Enrich with event data
            try:
                summary = event_repo.get_event_summary(job.job_id)
                job_dict['event_count'] = summary.get('total_events', 0)
                job_dict['has_failure'] = summary.get('by_status', {}).get('failure', 0) > 0

                latest = event_repo.get_latest_event(job.job_id)
                if latest:
                    job_dict['latest_event'] = {
                        'event_type': latest.event_type.value if hasattr(latest.event_type, 'value') else latest.event_type,
                        'summary': latest.checkpoint_name or ''
                    }
            except Exception:
                pass  # Keep defaults

            jobs.append(job_dict)  # Dict works directly in Jinja2 templates

        return templates.TemplateResponse("pages/jobs/list.html", {
            "request": request,
            "version": __version__,
            "nav_active": "/interface/jobs",
            "jobs": jobs,
            "stats": stats,
            "filters": {"status": status, "hours": hours}
        })

    except Exception as e:
        logger.error(f"Error loading job list: {e}")
        return HTMLResponse(f"<div class='error'>Error loading jobs: {str(e)}</div>")


@app.get("/interface/jobs/partial", response_class=HTMLResponse)
async def interface_jobs_partial(
    request: Request,
    status: str = None,
    hours: int = 24
):
    """
    HTMX partial - job cards only for auto-refresh.
    """
    try:
        from infrastructure import JobRepository, JobEventRepository
        from core.models import JobStatus
        from datetime import datetime, timezone, timedelta

        job_repo = JobRepository()
        event_repo = JobEventRepository()

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Get jobs with optional status filter
        status_filter = None
        if status:
            try:
                status_filter = JobStatus(status.upper())
            except ValueError:
                pass

        all_jobs = job_repo.list_jobs(status_filter=status_filter)

        # Filter by time and limit
        # Handle both timezone-aware and timezone-naive datetimes
        def job_in_range(job):
            if not job.created_at:
                return False
            job_time = job.created_at
            if job_time.tzinfo is None:
                job_time = job_time.replace(tzinfo=timezone.utc)
            return job_time >= cutoff

        filtered_jobs = [j for j in all_jobs if job_in_range(j)][:100]

        # Convert to enriched dicts for template (Pydantic boundary crossing)
        jobs = []
        for job in filtered_jobs:
            status_val = job.status.value.lower() if job.status else 'unknown'
            job_dict = {
                'job_id': job.job_id,
                'job_type': job.job_type,
                'status': status_val,
                'current_stage': job.stage,
                'total_stages': job.total_stages,
                'parameters': job.parameters,
                'created_at': job.created_at,
                'completed_at': job.updated_at if status_val == 'completed' else None,
                'event_count': 0,
                'has_failure': False,
                'latest_event': None
            }

            # Enrich with event data
            try:
                summary = event_repo.get_event_summary(job.job_id)
                job_dict['event_count'] = summary.get('total_events', 0)
                job_dict['has_failure'] = summary.get('by_status', {}).get('failure', 0) > 0

                latest = event_repo.get_latest_event(job.job_id)
                if latest:
                    job_dict['latest_event'] = {
                        'event_type': latest.event_type.value if hasattr(latest.event_type, 'value') else latest.event_type,
                        'summary': latest.checkpoint_name or ''
                    }
            except Exception:
                pass  # Keep defaults

            jobs.append(job_dict)

        # Render just the job cards
        cards_html = ""
        for job in jobs:
            cards_html += templates.get_template("components/_job_card.html").render(job=job)

        if not jobs:
            cards_html = '''
            <div class="empty-state">
                <div class="empty-icon">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        <line x1="9" y1="9" x2="15" y2="15"></line>
                        <line x1="15" y1="9" x2="9" y2="15"></line>
                    </svg>
                </div>
                <h3>No Jobs Found</h3>
                <p>No jobs match your current filters.</p>
            </div>
            '''

        return HTMLResponse(cards_html)

    except Exception as e:
        return HTMLResponse(f'<div class="error">Error: {str(e)}</div>')


@app.get("/interface/jobs/{job_id}", response_class=HTMLResponse)
async def interface_job_detail(request: Request, job_id: str):
    """
    Job detail page with stage progress and event timeline.
    """
    try:
        from infrastructure import JobRepository, TaskRepository, JobEventRepository

        job_repo = JobRepository()
        task_repo = TaskRepository()
        event_repo = JobEventRepository()

        # Get job
        job = job_repo.get_job(job_id)
        if not job:
            return HTMLResponse(f'''
            <div class="container">
                <div class="error-state">
                    <h2>Job Not Found</h2>
                    <p>No job found with ID: {job_id[:32]}...</p>
                    <a href="/interface/jobs" class="btn btn-primary">Back to Job List</a>
                </div>
            </div>
            ''', status_code=404)

        # Get tasks for stage progress
        tasks = task_repo.get_tasks_for_job(job_id)

        # Group tasks by stage
        stages = {}
        for task in tasks:
            stage = task.stage or 1
            if stage not in stages:
                stages[stage] = {"total": 0, "completed": 0, "failed": 0}
            stages[stage]["total"] += 1
            task_status = (task.status.value if hasattr(task.status, 'value') else str(task.status)).lower() if task.status else ''
            if task_status == "completed":
                stages[stage]["completed"] += 1
            elif task_status == "failed":
                stages[stage]["failed"] += 1

        # Get events
        events = event_repo.get_events_timeline(job_id, limit=100)
        summary = event_repo.get_event_summary(job_id)
        failure_context = event_repo.get_failure_context(job_id)

        # Get orchestrator URL for API links (Function App hosts job/task APIs)
        from config import get_config
        config = get_config()
        orchestrator_url = getattr(config, 'etl_app_base_url', '') or ''

        return templates.TemplateResponse("pages/jobs/detail.html", {
            "request": request,
            "version": __version__,
            "nav_active": "/interface/jobs",
            "job": job,
            "job_id": job_id,
            "stages": stages,
            "events": events,
            "summary": summary,
            "failure_context": failure_context,
            "orchestrator_url": orchestrator_url
        })

    except Exception as e:
        logger.error(f"Error loading job detail: {e}")
        return HTMLResponse(f"<div class='error'>Error loading job: {str(e)}</div>")


# ============================================================================
# JOB EVENTS INTERFACE (23 JAN 2026 - Execution Timeline)
# ============================================================================

@app.get("/interface/jobs/{job_id}/events", response_class=HTMLResponse)
async def interface_job_events(request: Request, job_id: str):
    """
    Job events page showing execution timeline.

    Full-page view with event timeline and failure context.
    """
    try:
        from infrastructure import JobEventRepository

        event_repo = JobEventRepository()

        # Get events and failure context
        events = event_repo.get_events_timeline(job_id, limit=100)
        failure_context = event_repo.get_failure_context(job_id)
        summary = event_repo.get_event_summary(job_id)

        # Get orchestrator URL for API links (Function App hosts job/task APIs)
        from config import get_config
        config = get_config()
        orchestrator_url = getattr(config, 'etl_app_base_url', '') or ''

        return templates.TemplateResponse("pages/jobs/events.html", {
            "request": request,
            "version": __version__,
            "nav_active": "/interface/jobs",
            "job_id": job_id,
            "events": events,
            "failure_context": failure_context,
            "summary": summary,
            "orchestrator_url": orchestrator_url
        })

    except Exception as e:
        return HTMLResponse(f"<div class='error'>Error loading events: {str(e)}</div>")


@app.get("/interface/jobs/{job_id}/events/partial", response_class=HTMLResponse)
async def interface_job_events_partial(request: Request, job_id: str, filter: str = None):
    """
    HTMX partial - event timeline rows only.

    Used for auto-refresh and filtering without full page reload.

    Query params:
        filter: Filter type (job, stage, task, failure)
    """
    try:
        from infrastructure import JobEventRepository
        from core.models.job_event import JobEventType

        event_repo = JobEventRepository()
        events = event_repo.get_events_timeline(job_id, limit=100)

        # Apply filter if specified
        if filter == 'job':
            events = [e for e in events if e['event_type'].startswith('job_')]
        elif filter == 'stage':
            events = [e for e in events if e['event_type'].startswith('stage_')]
        elif filter == 'task':
            events = [e for e in events if e['task_id'] is not None]
        elif filter == 'failure':
            events = [e for e in events if e['event_status'] == 'failure']

        # Render just the rows
        rows_html = ""
        for event in events:
            rows_html += templates.get_template("components/_event_row.html").render(
                event=event
            )

        if not events:
            rows_html = '<div class="timeline-empty">No events found</div>'

        return HTMLResponse(rows_html)

    except Exception as e:
        return HTMLResponse(f'<div class="timeline-error">Error: {str(e)}</div>')


@app.get("/interface/jobs/{job_id}/events/failure", response_class=HTMLResponse)
async def interface_job_failure_context(request: Request, job_id: str):
    """
    HTMX partial - failure context panel.

    Shows the failure event and preceding events for debugging.
    """
    try:
        from infrastructure import JobEventRepository

        event_repo = JobEventRepository()
        failure_context = event_repo.get_failure_context(job_id)

        return templates.TemplateResponse("components/_failure_context.html", {
            "request": request,
            "job_id": job_id,
            "has_failure": failure_context['has_failure'],
            "failure_event": failure_context.get('failure_event'),
            "preceding_events": failure_context.get('preceding_events', [])
        })

    except Exception as e:
        return HTMLResponse(f'<div class="failure-error">Error: {str(e)}</div>')


# ============================================================================
# TASKS INTERFACE (25 JAN 2026 - Phase 2 Core Routes)
# ============================================================================

@app.get("/interface/tasks", response_class=HTMLResponse)
async def interface_tasks_list(
    request: Request,
    job_id: str = None,
    task_id: str = None
):
    """
    Task monitor page - shows tasks for a specific job.

    Query params:
        job_id: Job ID to view tasks for
        task_id: Optional specific task ID to highlight
    """
    try:
        from templates_utils import render_template

        # If no job_id, show the job selector
        if not job_id:
            return render_template(
                request,
                "pages/tasks/list.html",
                job_id=None,
                nav_active="/interface/tasks"
            )

        from infrastructure import JobRepository, TaskRepository

        job_repo = JobRepository()
        task_repo = TaskRepository()

        # Get job info
        job = job_repo.get_job(job_id)

        # Get tasks for the job
        tasks = task_repo.get_tasks_for_job(job_id)

        # Group tasks by stage
        tasks_by_stage = {}
        task_stats = {"pending": 0, "queued": 0, "processing": 0, "completed": 0, "failed": 0}

        for task in tasks:
            stage = task.stage or 1
            if stage not in tasks_by_stage:
                tasks_by_stage[stage] = []
            tasks_by_stage[stage].append(task)

            # Count by status (handle enum or string)
            raw_status = task.status.value if hasattr(task.status, 'value') else task.status
            status = (raw_status or "pending").lower()
            if status in task_stats:
                task_stats[status] += 1

        return render_template(
            request,
            "pages/tasks/list.html",
            job_id=job_id,
            job=job,
            tasks=tasks,
            tasks_by_stage=tasks_by_stage,
            task_stats=task_stats,
            highlight_task_id=task_id,
            nav_active="/interface/tasks"
        )

    except Exception as e:
        logger.error(f"Error loading tasks: {e}")
        return HTMLResponse(f"<div class='error'>Error loading tasks: {str(e)}</div>")


@app.get("/interface/tasks/partial", response_class=HTMLResponse)
async def interface_tasks_partial(request: Request, job_id: str):
    """
    HTMX partial - tasks list for auto-refresh.

    Returns just the stages container content for HTMX swap.
    """
    try:
        from infrastructure import TaskRepository

        task_repo = TaskRepository()
        tasks = task_repo.get_tasks_for_job(job_id)

        # Group tasks by stage
        tasks_by_stage = {}
        for task in tasks:
            stage = task.stage or 1
            if stage not in tasks_by_stage:
                tasks_by_stage[stage] = []
            tasks_by_stage[stage].append(task)

        # Build HTML for stages (inline for partial response)
        # Helper to safely get status string from enum or string
        def get_status_str(status):
            if status is None:
                return ''
            return (status.value if hasattr(status, 'value') else str(status)).lower()

        html_parts = []
        for stage_num in sorted(tasks_by_stage.keys()):
            stage_tasks = tasks_by_stage[stage_num]
            completed_count = sum(1 for t in stage_tasks if get_status_str(t.status) == 'completed')
            failed_count = sum(1 for t in stage_tasks if get_status_str(t.status) == 'failed')
            processing_count = sum(1 for t in stage_tasks if get_status_str(t.status) == 'processing')

            # Stage icon
            if completed_count == len(stage_tasks):
                icon_html = '''<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ds-status-completed-fg)" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="8 12 11 15 16 9"></polyline>
                </svg>'''
            elif processing_count > 0:
                icon_html = '<span class="stage-dot pulse"></span>'
            else:
                icon_html = '<span class="stage-dot"></span>'

            # Build task rows
            task_rows = []
            for task in stage_tasks:
                status = get_status_str(task.status) or 'pending'
                status_letter = status[0].upper() if status else 'P'
                duration_str = '--'
                if hasattr(task, 'duration_ms') and task.duration_ms:
                    if task.duration_ms > 60000:
                        duration_str = f"{task.duration_ms / 60000:.1f}m"
                    elif task.duration_ms > 1000:
                        duration_str = f"{task.duration_ms / 1000:.1f}s"
                    else:
                        duration_str = f"{task.duration_ms}ms"
                elif status == 'processing':
                    duration_str = '<span class="processing-indicator">Running...</span>'

                created_str = str(task.created_at)[:19].replace('T', ' ') if task.created_at else 'N/A'

                task_rows.append(f'''
                <tr class="task-row task-status-{status}" data-task-id="{task.task_id}">
                    <td class="col-status">
                        <span class="status-badge status-{status}">
                            {'<span class="status-dot pulse"></span>' if status == 'processing' else ''}
                            {status_letter}
                        </span>
                    </td>
                    <td class="col-task-id"><code title="{task.task_id}">{task.task_id[:16]}...</code></td>
                    <td class="col-type">{(task.task_type or '').replace('_', ' ').title()}</td>
                    <td class="col-time">{created_str}</td>
                    <td class="col-duration">{duration_str}</td>
                    <td class="col-actions">
                        <button class="btn btn-sm btn-secondary" onclick="toggleTaskDetails('{task.task_id}')">View</button>
                    </td>
                </tr>
                ''')

            failed_str = f'<span class="failed-count">({failed_count} failed)</span>' if failed_count > 0 else ''

            html_parts.append(f'''
            <div class="stage-section">
                <div class="stage-header" onclick="toggleStage({stage_num})">
                    <div class="stage-title">
                        <span class="stage-icon">{icon_html}</span>
                        <span>Stage {stage_num}</span>
                        <span class="stage-task-count">{len(stage_tasks)} tasks</span>
                    </div>
                    <div class="stage-progress">
                        <span class="progress-text">{completed_count}/{len(stage_tasks)}</span>
                        {failed_str}
                        <svg class="collapse-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </div>
                </div>
                <div class="stage-content" id="stage-{stage_num}-content">
                    <table class="tasks-table">
                        <thead>
                            <tr>
                                <th class="col-status">Status</th>
                                <th class="col-task-id">Task ID</th>
                                <th class="col-type">Type</th>
                                <th class="col-time">Created</th>
                                <th class="col-duration">Duration</th>
                                <th class="col-actions">Details</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(task_rows)}
                        </tbody>
                    </table>
                </div>
            </div>
            ''')

        return HTMLResponse(''.join(html_parts))

    except Exception as e:
        return HTMLResponse(f'<div class="error">Error loading tasks: {str(e)}</div>')


# ============================================================================
# FUNCTION APP PROXY (GAP-01: Cross-System Health)
# ============================================================================

@app.get("/api/proxy/fa/health")
async def proxy_function_app_health():
    """
    Proxy endpoint to fetch Function App health status.

    This allows the Docker Worker UI to display Function App health alongside
    its own health, enabling cross-system visibility from a single dashboard.

    Returns:
        Function App health JSON or error status
    """
    import httpx
    from config import get_config

    try:
        config = get_config()
        fa_url = config.platform.etl_app_base_url

        if not fa_url:
            return {
                "status": "unknown",
                "error": "Function App URL not configured",
                "_source": "function_app"
            }

        # Normalize URL
        if not fa_url.startswith("http"):
            fa_url = f"https://{fa_url}"

        health_url = f"{fa_url}/api/health"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(health_url)
            response.raise_for_status()
            data = response.json()
            data["_source"] = "function_app"
            data["_proxy_url"] = fa_url
            return data

    except httpx.TimeoutException:
        return {
            "status": "unreachable",
            "error": "Function App health check timed out (30s)",
            "_source": "function_app"
        }
    except httpx.HTTPStatusError as e:
        return {
            "status": "unhealthy",
            "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            "_source": "function_app"
        }
    except Exception as e:
        logger.warning(f"Function App health proxy failed: {e}")
        return {
            "status": "unreachable",
            "error": str(e),
            "_source": "function_app"
        }


@app.get("/api/proxy/fa/dbadmin/stats")
async def proxy_function_app_dbstats():
    """
    Proxy endpoint to fetch Function App database stats.

    Returns:
        Function App database stats JSON or error status
    """
    import httpx
    from config import get_config

    try:
        config = get_config()
        fa_url = config.platform.etl_app_base_url

        if not fa_url:
            return {"error": "Function App URL not configured"}

        if not fa_url.startswith("http"):
            fa_url = f"https://{fa_url}"

        stats_url = f"{fa_url}/api/dbadmin/stats"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(stats_url)
            response.raise_for_status()
            return response.json()

    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# QUEUE INFRASTRUCTURE VISIBILITY (GAP-02: Queue Status)
# ============================================================================

@app.get("/api/queues/status")
async def get_queue_status():
    """
    Get Service Bus queue status including message counts and dead-letter counts.

    Returns status for all three V0.8 queues:
    - geospatial-jobs: Job orchestration (Orchestrator listens)
    - container-tasks: Docker Worker (heavy operations)
    - functionapp-tasks: Function App Worker (lightweight operations)

    Each queue includes:
    - active_message_count: Messages waiting to be processed
    - dead_letter_message_count: Failed messages in DLQ
    - scheduled_message_count: Messages scheduled for future delivery
    - listener: Which system processes this queue
    - listener_url: URL to the listener interface (placeholder for now)

    Returns:
        Queue status for all configured queues
    """
    from config import get_config
    from config.defaults import QueueDefaults

    try:
        config = get_config()

        # Queue configuration with listeners
        queue_configs = [
            {
                "name": QueueDefaults.JOBS_QUEUE,
                "display_name": "Jobs Queue",
                "description": "Job orchestration and stage_complete signals",
                "listener": "Orchestrator (Function App)",
                "listener_url": "/interface/jobs",
                "icon": "&#x1F4CB;"
            },
            {
                "name": QueueDefaults.CONTAINER_TASKS_QUEUE,
                "display_name": "Container Tasks",
                "description": "Docker worker - heavy operations (GDAL, geopandas)",
                "listener": "Docker Worker",
                "listener_url": "/interface/tasks",
                "icon": "&#x1F433;"
            },
            {
                "name": QueueDefaults.FUNCTIONAPP_TASKS_QUEUE,
                "display_name": "Function App Tasks",
                "description": "Function App worker - lightweight DB operations",
                "listener": "Function App Worker",
                "listener_url": None,  # FA task interface not available from Docker
                "icon": "&#x26A1;"
            },
        ]

        # Get Service Bus admin client
        from infrastructure.service_bus import get_service_bus_repository
        from azure.servicebus.management import ServiceBusAdministrationClient
        from azure.identity import DefaultAzureCredential
        from azure.core.exceptions import ResourceNotFoundError

        # Create admin client
        connection_string = config.service_bus_connection_string
        namespace = config.service_bus_namespace

        if connection_string:
            admin_client = ServiceBusAdministrationClient.from_connection_string(connection_string)
        elif namespace:
            admin_client = ServiceBusAdministrationClient(
                fully_qualified_namespace=namespace,
                credential=DefaultAzureCredential()
            )
        else:
            return {
                "status": "error",
                "error": "Service Bus not configured",
                "queues": []
            }

        queues = []

        with admin_client:
            for queue_config in queue_configs:
                queue_name = queue_config["name"]
                try:
                    # Get queue runtime properties (includes message counts)
                    runtime_props = admin_client.get_queue_runtime_properties(queue_name)

                    queues.append({
                        "name": queue_name,
                        "display_name": queue_config["display_name"],
                        "description": queue_config["description"],
                        "listener": queue_config["listener"],
                        "listener_url": queue_config["listener_url"],
                        "icon": queue_config["icon"],
                        "status": "healthy",
                        "active_message_count": runtime_props.active_message_count,
                        "dead_letter_message_count": runtime_props.dead_letter_message_count,
                        "scheduled_message_count": runtime_props.scheduled_message_count,
                        "transfer_message_count": runtime_props.transfer_message_count,
                        "transfer_dead_letter_message_count": runtime_props.transfer_dead_letter_message_count,
                        "total_message_count": runtime_props.total_message_count,
                        "size_in_bytes": runtime_props.size_in_bytes,
                        "accessed_at": runtime_props.accessed_at.isoformat() if runtime_props.accessed_at else None,
                        "updated_at": runtime_props.updated_at.isoformat() if runtime_props.updated_at else None,
                    })

                except ResourceNotFoundError:
                    queues.append({
                        "name": queue_name,
                        "display_name": queue_config["display_name"],
                        "description": queue_config["description"],
                        "listener": queue_config["listener"],
                        "listener_url": queue_config["listener_url"],
                        "icon": queue_config["icon"],
                        "status": "not_found",
                        "error": f"Queue '{queue_name}' does not exist",
                        "active_message_count": 0,
                        "dead_letter_message_count": 0,
                    })

                except Exception as e:
                    queues.append({
                        "name": queue_name,
                        "display_name": queue_config["display_name"],
                        "description": queue_config["description"],
                        "listener": queue_config["listener"],
                        "listener_url": queue_config["listener_url"],
                        "icon": queue_config["icon"],
                        "status": "error",
                        "error": str(e),
                        "active_message_count": 0,
                        "dead_letter_message_count": 0,
                    })

        # Calculate totals
        total_active = sum(q.get("active_message_count", 0) for q in queues)
        total_dlq = sum(q.get("dead_letter_message_count", 0) for q in queues)
        overall_status = "healthy"
        if any(q.get("status") == "error" for q in queues):
            overall_status = "error"
        elif any(q.get("status") == "not_found" for q in queues):
            overall_status = "warning"
        elif total_dlq > 0:
            overall_status = "warning"

        return {
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_queues": len(queues),
                "total_active_messages": total_active,
                "total_dead_letter_messages": total_dlq,
            },
            "queues": queues,
            "namespace": namespace or "(connection string)",
        }

    except Exception as e:
        logger.error(f"Error fetching queue status: {e}")
        return {
            "status": "error",
            "error": str(e),
            "queues": []
        }


@app.post("/api/queues/{queue_name}/purge")
async def purge_queue(queue_name: str, confirm: str = None, target: str = "active"):
    """
    Purge messages from a Service Bus queue.

    This is a destructive operation - messages are permanently deleted.
    Requires confirm=yes query parameter.

    Args:
        queue_name: Name of the queue to purge
        confirm: Must be "yes" to proceed
        target: "active" (default), "dlq" (dead-letter), or "all"

    Returns:
        Result of the purge operation
    """
    from config import get_config
    from infrastructure.service_bus import get_service_bus_repository

    if confirm != "yes":
        return JSONResponse(
            status_code=400,
            content={
                "error": "Destructive operation requires confirm=yes",
                "warning": "This will permanently delete all messages from the queue",
                "usage": f"POST /api/queues/{queue_name}/purge?confirm=yes&target={target}"
            }
        )

    if target not in ("active", "dlq", "all"):
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid target '{target}'. Must be 'active', 'dlq', or 'all'"}
        )

    try:
        config = get_config()
        sb_repo = get_service_bus_repository()

        result = {
            "queue_name": queue_name,
            "target": target,
            "active_cleared": 0,
            "dlq_cleared": 0,
        }

        # Clear active messages
        if target in ("active", "all"):
            logger.warning(f"🗑️ Purging active messages from queue: {queue_name}")
            active_cleared = 0
            receiver = sb_repo._get_receiver(queue_name)
            try:
                with receiver:
                    while True:
                        messages = receiver.receive_messages(max_message_count=100, max_wait_time=2)
                        if not messages:
                            break
                        for msg in messages:
                            receiver.complete_message(msg)
                            active_cleared += 1
            except Exception as e:
                logger.error(f"Error clearing active queue: {e}")
            result["active_cleared"] = active_cleared

        # Clear dead-letter queue
        if target in ("dlq", "all"):
            logger.warning(f"🗑️ Purging DLQ messages from queue: {queue_name}")
            dlq_cleared = 0
            # DLQ is accessed via special sub-queue path
            dlq_name = f"{queue_name}/$deadletterqueue"
            try:
                dlq_receiver = sb_repo.client.get_queue_receiver(dlq_name)
                with dlq_receiver:
                    while True:
                        messages = dlq_receiver.receive_messages(max_message_count=100, max_wait_time=2)
                        if not messages:
                            break
                        for msg in messages:
                            dlq_receiver.complete_message(msg)
                            dlq_cleared += 1
            except Exception as e:
                logger.error(f"Error clearing DLQ: {e}")
            result["dlq_cleared"] = dlq_cleared

        total_cleared = result["active_cleared"] + result["dlq_cleared"]
        result["total_cleared"] = total_cleared
        result["status"] = "success" if total_cleared > 0 else "empty"
        result["message"] = f"Cleared {total_cleared} messages from {queue_name}"

        logger.warning(
            f"🗑️ Queue purge complete: {queue_name}, active={result['active_cleared']}, dlq={result['dlq_cleared']}"
        )

        return result

    except Exception as e:
        logger.error(f"Error purging queue {queue_name}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "queue_name": queue_name}
        )


# ============================================================================
# APPLICATION INSIGHTS LOGS (GAP-03: Log Viewing)
# ============================================================================

# Application Insights App ID for rmhazuregeoapi
# This should match the Function App that logs are sent to
APP_INSIGHTS_APP_ID = "d3af3d37-cfe3-411f-adef-bc540181cbca"


@app.get("/interface/logs", response_class=HTMLResponse)
async def interface_logs(request: Request, job_id: str = None):
    """
    Standalone log viewer page.

    Query params:
        job_id: Optional - pre-filter logs by job ID
    """
    try:
        from templates_utils import render_template

        return render_template(
            request,
            "pages/logs/index.html",
            job_id=job_id,
            nav_active="/interface/logs"
        )
    except Exception as e:
        logger.error(f"Error loading logs page: {e}")
        return HTMLResponse(f"<div class='error'>Error loading logs page: {str(e)}</div>")


@app.get("/api/logs/query")
async def query_logs(
    time_range: str = "15m",
    severity: int = 1,
    source: str = "all",
    limit: int = 100,
    job_id: str = None,
    search: str = None
):
    """
    Query Application Insights logs.

    Uses the Azure Monitor REST API to fetch logs from Application Insights.
    Requires Azure credentials (DefaultAzureCredential) with access to App Insights.

    Args:
        time_range: Time range for logs (5m, 15m, 30m, 1h, 3h, 6h, 24h)
        severity: Minimum severity level (0=Verbose, 1=Info, 2=Warning, 3=Error, 4=Critical)
        source: Log source (all, traces, requests, exceptions, dependencies)
        limit: Maximum number of logs to return
        job_id: Optional job ID to filter by
        search: Optional text search in messages

    Returns:
        List of log entries with metadata
    """
    import httpx
    from azure.identity import DefaultAzureCredential

    try:
        # Validate parameters
        valid_ranges = {"5m", "15m", "30m", "1h", "3h", "6h", "24h"}
        if time_range not in valid_ranges:
            time_range = "15m"

        limit = min(max(limit, 10), 1000)  # Clamp between 10 and 1000

        # Build KQL query
        if source == "all":
            table = "union traces, requests, exceptions"
        else:
            table = source

        # Base query
        kql_parts = [
            table,
            f"| where timestamp >= ago({time_range})",
            f"| where severityLevel >= {severity}"
        ]

        # Add job_id filter
        if job_id:
            kql_parts.append(f'| where message contains "{job_id}" or customDimensions contains "{job_id}"')

        # Add text search
        if search:
            # Handle OR in search
            if " OR " in search:
                terms = [t.strip() for t in search.split(" OR ")]
                search_clause = " or ".join([f'message contains "{t}"' for t in terms])
                kql_parts.append(f"| where {search_clause}")
            else:
                kql_parts.append(f'| where message contains "{search}"')

        # Order and limit
        kql_parts.extend([
            "| order by timestamp desc",
            f"| take {limit}",
            "| project timestamp, message, severityLevel, operation_Name, customDimensions, "
            "itemType, resultCode, duration, success, outerMessage, details"
        ])

        kql_query = "\n".join(kql_parts)
        logger.info(f"Executing App Insights query: time_range={time_range}, severity>={severity}, source={source}")

        # Get Azure token for Application Insights API
        credential = DefaultAzureCredential()
        token = credential.get_token("https://api.applicationinsights.io/.default")

        # Query Application Insights REST API
        api_url = f"https://api.applicationinsights.io/v1/apps/{APP_INSIGHTS_APP_ID}/query"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                api_url,
                params={"query": kql_query},
                headers={"Authorization": f"Bearer {token.token}"}
            )

            if response.status_code != 200:
                error_text = response.text[:500]
                logger.error(f"App Insights query failed: {response.status_code} - {error_text}")
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": f"Application Insights query failed: {error_text}"}
                )

            result = response.json()

        # Parse results
        logs = []
        error_count = 0
        warning_count = 0
        info_count = 0

        if "tables" in result and result["tables"]:
            table_data = result["tables"][0]
            columns = [col["name"] for col in table_data.get("columns", [])]
            rows = table_data.get("rows", [])

            for row in rows:
                row_dict = dict(zip(columns, row))

                severity_level = row_dict.get("severityLevel", 1)
                if severity_level >= 3:
                    error_count += 1
                elif severity_level == 2:
                    warning_count += 1
                else:
                    info_count += 1

                # Determine source from itemType
                item_type = row_dict.get("itemType", "trace")
                source_map = {
                    "trace": "traces",
                    "request": "requests",
                    "exception": "exceptions",
                    "dependency": "dependencies"
                }

                # Parse customDimensions if it's a string
                custom_dims = row_dict.get("customDimensions")
                if isinstance(custom_dims, str):
                    try:
                        import json
                        custom_dims = json.loads(custom_dims)
                    except:
                        custom_dims = {}

                logs.append({
                    "timestamp": row_dict.get("timestamp"),
                    "message": row_dict.get("message") or row_dict.get("outerMessage") or "",
                    "severity_level": severity_level,
                    "operation_name": row_dict.get("operation_Name"),
                    "custom_dimensions": custom_dims or {},
                    "source": source_map.get(item_type, item_type),
                    "result_code": row_dict.get("resultCode"),
                    "duration": row_dict.get("duration"),
                    "success": row_dict.get("success"),
                    "details": row_dict.get("details"),
                })

        return {
            "status": "success",
            "total": len(logs),
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count,
            "query_time": time_range,
            "source": "Application Insights",
            "logs": logs
        }

    except Exception as e:
        logger.error(f"Error querying Application Insights: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ============================================================================
# RASTER VIEWER ENDPOINTS
# ============================================================================

@app.get("/interface/raster/viewer", response_class=HTMLResponse)
@app.get("/interface/raster/viewer/{collection_id}", response_class=HTMLResponse)
def raster_viewer_page(
    request: Request,
    collection_id: str = None
):
    """
    Raster Curator interface for reviewing COG outputs.

    Provides a map-based viewer for inspecting raster data with:
    - Band selection and visualization controls
    - Statistics display (min/max/mean/percentiles)
    - Stretch controls (auto, percentile-based, custom)
    - Point query for pixel values
    - QA approval workflow integration

    Args:
        collection_id: Optional STAC collection ID to load

    Returns:
        HTML page with Leaflet map and sidebar controls
    """
    try:
        from templates_utils import render_template
        from config import get_config

        config = get_config()
        titiler_base_url = getattr(config, 'titiler_base_url', None) or ''

        # Get initial bbox from collection if available
        initial_bbox = None
        if collection_id:
            try:
                from repositories.stac_repository import STACRepository
                stac_repo = STACRepository()
                collection = stac_repo.get_collection(collection_id)
                if collection and 'extent' in collection:
                    spatial = collection['extent'].get('spatial', {})
                    bbox = spatial.get('bbox', [[]])[0]
                    if len(bbox) >= 4:
                        initial_bbox = bbox
            except Exception as e:
                logger.warning(f"Could not fetch collection bbox: {e}")

        return render_template(
            request,
            "pages/raster/viewer.html",
            collection_id=collection_id,
            titiler_base_url=titiler_base_url,
            initial_bbox=initial_bbox,
            nav_active="/interface/raster/viewer"
        )
    except Exception as e:
        logger.error(f"Error loading raster viewer: {e}")
        return HTMLResponse(f"<div class='error'>Error loading raster viewer: {str(e)}</div>")


@app.get("/api/raster/collections")
async def list_raster_collections():
    """
    List all raster collections from STAC catalog.

    Returns collections filtered to those with raster/COG assets.

    Returns:
        List of collections with id, title, item count
    """
    try:
        from repositories.stac_repository import STACRepository

        stac_repo = STACRepository()
        collections = stac_repo.get_collections()

        # Filter to raster collections (those with COG assets or raster type)
        raster_collections = []
        for col in collections:
            # Include if it has raster item_type or COG in description
            item_type = col.get('item_type', '')
            description = col.get('description', '').lower()

            if 'raster' in item_type.lower() or 'cog' in description or 'raster' in description:
                raster_collections.append({
                    'id': col.get('id'),
                    'title': col.get('title') or col.get('id'),
                    'description': col.get('description', '')[:100],
                    'item_count': col.get('item_count', 0)
                })
            else:
                # Include all for now - filter can be refined
                raster_collections.append({
                    'id': col.get('id'),
                    'title': col.get('title') or col.get('id'),
                    'description': col.get('description', '')[:100],
                    'item_count': col.get('item_count', 0)
                })

        return {
            "status": "success",
            "count": len(raster_collections),
            "collections": raster_collections
        }

    except Exception as e:
        logger.error(f"Error listing raster collections: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/raster/stats")
async def get_raster_stats(
    url: str,
    bidx: str = None
):
    """
    Proxy to TiTiler statistics endpoint.

    Fetches per-band statistics for a COG including:
    - min, max, mean, std
    - percentiles (p2, p5, p50, p95, p98)
    - histogram (optional)

    Args:
        url: URL of the COG file
        bidx: Optional band index (e.g., "1" or "1,2,3")

    Returns:
        Per-band statistics from TiTiler
    """
    import httpx
    from config import get_config

    try:
        config = get_config()
        titiler_base_url = getattr(config, 'titiler_base_url', None)

        if not titiler_base_url:
            return JSONResponse(
                status_code=503,
                content={"error": "TiTiler service not configured"}
            )

        # Build TiTiler statistics URL
        stats_url = f"{titiler_base_url}/cog/statistics"
        params = {"url": url}
        if bidx:
            params["bidx"] = bidx

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(stats_url, params=params)

            if response.status_code != 200:
                error_text = response.text[:500]
                logger.error(f"TiTiler stats request failed: {response.status_code} - {error_text}")
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": f"TiTiler request failed: {error_text}"}
                )

            stats = response.json()

        return {
            "status": "success",
            "url": url,
            "statistics": stats
        }

    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"error": "TiTiler request timed out"}
        )
    except Exception as e:
        logger.error(f"Error fetching raster stats: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/raster/info")
async def get_raster_info(url: str):
    """
    Proxy to TiTiler info endpoint.

    Fetches COG metadata including:
    - bounds, CRS, dimensions
    - band count and names
    - data type, nodata value

    Args:
        url: URL of the COG file

    Returns:
        COG metadata from TiTiler
    """
    import httpx
    from config import get_config

    try:
        config = get_config()
        titiler_base_url = getattr(config, 'titiler_base_url', None)

        if not titiler_base_url:
            return JSONResponse(
                status_code=503,
                content={"error": "TiTiler service not configured"}
            )

        # Build TiTiler info URL
        info_url = f"{titiler_base_url}/cog/info"
        params = {"url": url}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(info_url, params=params)

            if response.status_code != 200:
                error_text = response.text[:500]
                logger.error(f"TiTiler info request failed: {response.status_code} - {error_text}")
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": f"TiTiler request failed: {error_text}"}
                )

            info = response.json()

        return {
            "status": "success",
            "url": url,
            "info": info
        }

    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"error": "TiTiler request timed out"}
        )
    except Exception as e:
        logger.error(f"Error fetching raster info: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/raster/point")
async def get_raster_point_value(
    url: str,
    lon: float,
    lat: float
):
    """
    Proxy to TiTiler point query endpoint.

    Fetches pixel values at a specific coordinate.

    Args:
        url: URL of the COG file
        lon: Longitude
        lat: Latitude

    Returns:
        Pixel values for all bands at the given coordinate
    """
    import httpx
    from config import get_config

    try:
        config = get_config()
        titiler_base_url = getattr(config, 'titiler_base_url', None)

        if not titiler_base_url:
            return JSONResponse(
                status_code=503,
                content={"error": "TiTiler service not configured"}
            )

        # Build TiTiler point URL
        point_url = f"{titiler_base_url}/cog/point/{lon},{lat}"
        params = {"url": url}

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(point_url, params=params)

            if response.status_code != 200:
                error_text = response.text[:500]
                logger.error(f"TiTiler point request failed: {response.status_code} - {error_text}")
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": f"TiTiler request failed: {error_text}"}
                )

            point_data = response.json()

        return {
            "status": "success",
            "lon": lon,
            "lat": lat,
            "values": point_data.get("values", []),
            "band_names": point_data.get("band_names", [])
        }

    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"error": "TiTiler request timed out"}
        )
    except Exception as e:
        logger.error(f"Error fetching point value: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ============================================================================
# VECTOR VIEWER ENDPOINTS
# ============================================================================

@app.get("/interface/vector/viewer", response_class=HTMLResponse)
@app.get("/interface/vector/viewer/{collection_id}", response_class=HTMLResponse)
def vector_viewer_page(
    request: Request,
    collection_id: str = None
):
    """
    Vector Curator interface for reviewing vector data outputs.

    Provides a MapLibre-based viewer for inspecting vector data with:
    - MVT tiles for high-performance rendering
    - GeoJSON mode for full attribute access
    - Styling controls (fill, stroke, opacity)
    - Feature inspection on click
    - Schema/attribute display
    - QA approval workflow integration

    Args:
        collection_id: Optional OGC collection ID to load

    Returns:
        HTML page with MapLibre map and sidebar controls
    """
    try:
        from templates_utils import render_template
        from config import get_config

        config = get_config()
        tipg_base_url = getattr(config, 'tipg_base_url', None) or ''

        # Get initial bbox from collection via TiPG
        initial_bbox = None
        if collection_id:
            try:
                import httpx
                # Ensure schema-qualified name for TiPG
                tipg_collection_id = collection_id if '.' in collection_id else f"geo.{collection_id}"
                collection_url = f"{tipg_base_url}/collections/{tipg_collection_id}"
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(collection_url)
                    if resp.status_code == 200:
                        collection = resp.json()
                        if 'extent' in collection:
                            spatial = collection['extent'].get('spatial', {})
                            bbox = spatial.get('bbox', [[]])[0]
                            if len(bbox) >= 4:
                                initial_bbox = bbox
            except Exception as e:
                logger.warning(f"Could not fetch collection bbox from TiPG: {e}")

        return render_template(
            request,
            "pages/vector/viewer.html",
            collection_id=collection_id,
            tipg_base_url=tipg_base_url,
            initial_bbox=initial_bbox,
            nav_active="/interface/vector/viewer"
        )
    except Exception as e:
        logger.error(f"Error loading vector viewer: {e}")
        return HTMLResponse(f"<div class='error'>Error loading vector viewer: {str(e)}</div>")


@app.get("/api/vector/collections")
async def list_vector_collections():
    """
    List all vector collections from TiPG.

    Proxies to TiPG /vector/collections endpoint.

    Returns:
        List of collections with id, title, feature count
    """
    try:
        import httpx
        from config import get_config

        config = get_config()
        tipg_base_url = getattr(config, 'tipg_base_url', '') or ''

        if not tipg_base_url:
            return JSONResponse(
                status_code=503,
                content={"error": "TiPG URL not configured"}
            )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{tipg_base_url}/collections")

            if resp.status_code != 200:
                return JSONResponse(
                    status_code=resp.status_code,
                    content={"error": f"TiPG returned {resp.status_code}"}
                )

            data = resp.json()
            collections = data.get('collections', [])

            vector_collections = []
            for col in collections:
                vector_collections.append({
                    'id': col.get('id'),
                    'title': col.get('title') or col.get('id'),
                    'description': col.get('description', '')[:100] if col.get('description') else '',
                    'feature_count': col.get('numberMatched') or col.get('context', {}).get('matched')
                })

            return {
                "status": "success",
                "count": len(vector_collections),
                "collections": vector_collections
            }

    except Exception as e:
        logger.error(f"Error listing vector collections from TiPG: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/vector/collection/{collection_id}")
async def get_vector_collection(collection_id: str):
    """
    Get vector collection metadata from TiPG.

    Args:
        collection_id: Collection ID (table name)

    Returns:
        Collection metadata including extent, CRS, schema
    """
    try:
        import httpx
        from config import get_config

        config = get_config()
        tipg_base_url = getattr(config, 'tipg_base_url', '') or ''

        if not tipg_base_url:
            return JSONResponse(
                status_code=503,
                content={"error": "TiPG URL not configured"}
            )

        # Ensure schema-qualified name for TiPG
        tipg_collection_id = collection_id if '.' in collection_id else f"geo.{collection_id}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{tipg_base_url}/collections/{tipg_collection_id}")

            if resp.status_code == 404:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"Collection '{collection_id}' not found"}
                )

            if resp.status_code != 200:
                return JSONResponse(
                    status_code=resp.status_code,
                    content={"error": f"TiPG returned {resp.status_code}"}
                )

            collection = resp.json()
            return {
                "status": "success",
                "collection": collection
            }

    except Exception as e:
        logger.error(f"Error fetching collection {collection_id} from TiPG: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/vector/features/{collection_id}")
async def get_vector_features(
    collection_id: str,
    limit: int = 100,
    offset: int = 0,
    bbox: str = None
):
    """
    Get vector features from a collection via TiPG.

    Proxies to TiPG /collections/{id}/items endpoint.

    Args:
        collection_id: Collection ID (table name)
        limit: Maximum features to return (default 100)
        offset: Pagination offset
        bbox: Bounding box filter (minx,miny,maxx,maxy)

    Returns:
        GeoJSON FeatureCollection
    """
    try:
        import httpx
        from config import get_config

        config = get_config()
        tipg_base_url = getattr(config, 'tipg_base_url', '') or ''

        if not tipg_base_url:
            return JSONResponse(
                status_code=503,
                content={"error": "TiPG URL not configured"}
            )

        # Ensure schema-qualified name for TiPG
        tipg_collection_id = collection_id if '.' in collection_id else f"geo.{collection_id}"

        # Build query params
        params = {"limit": limit, "offset": offset}
        if bbox:
            params["bbox"] = bbox

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{tipg_base_url}/collections/{tipg_collection_id}/items",
                params=params
            )

            if resp.status_code != 200:
                return JSONResponse(
                    status_code=resp.status_code,
                    content={"error": f"TiPG returned {resp.status_code}"}
                )

            return resp.json()

    except Exception as e:
        logger.error(f"Error fetching features from {collection_id} via TiPG: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
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

    Format matches Function App /api/health for compatibility with health.js UI.

    Returns:
        Detailed health status with components structure
    """
    import platform
    import psutil

    from infrastructure.auth import get_token_status
    from config import get_config, __version__

    config = get_config()
    timestamp = datetime.now(timezone.utc)

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
        "instance_id_short": os.environ.get("WEBSITE_INSTANCE_ID", "local")[:8],
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

    # Connection pool stats (F7.18)
    try:
        from infrastructure.connection_pool import ConnectionPoolManager
        pool_stats = ConnectionPoolManager.get_pool_stats()
    except Exception as e:
        pool_stats = {"error": str(e)}

    # ETL mount status (V0.8)
    etl_mount_info = _etl_mount_status or {}

    # Queue worker status
    queue_status = queue_worker.get_status()
    token_refresh_status = token_refresh_worker.get_status()

    # =========================================================================
    # BUILD COMPONENTS (health.js compatible format)
    # =========================================================================
    # Each component needs: status, description, details, checked_at
    # _source tag indicates grouping: "docker_worker" or "function_app"

    components = {}

    # =========================================================================
    # DOCKER WORKER CORE COMPONENTS
    # =========================================================================

    # Runtime component (Container environment - primary Docker Worker component)
    components["runtime"] = {
        "status": "healthy",
        "description": "Docker container runtime environment",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": {
            "hardware": hardware,
            "instance": instance,
            "process": process_info,
            "memory": memory_stats,
            "capacity": capacity,
        }
    }

    # ETL Mount component (V0.8 - critical for large file processing)
    mount_enabled = etl_mount_info.get("mount_enabled", False)
    mount_validated = etl_mount_info.get("validated", False)
    mount_degraded = etl_mount_info.get("degraded", False)
    if mount_enabled and mount_validated:
        mount_status = "healthy"
    elif mount_degraded:
        mount_status = "warning"
    elif not mount_enabled:
        mount_status = "disabled"
    else:
        mount_status = "unhealthy"

    components["etl_mount"] = {
        "status": mount_status,
        "description": "Azure Files mount for large raster processing",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": {
            "mount_enabled": mount_enabled,
            "mount_path": etl_mount_info.get("mount_path", "N/A"),
            "validated": mount_validated,
            "disk_space": etl_mount_info.get("disk_space"),
            "message": etl_mount_info.get("message"),
            "error": etl_mount_info.get("error"),
        }
    }

    # Queue Worker component (Service Bus consumer)
    queue_running = queue_status.get("running", False)
    components["queue_worker"] = {
        "status": "healthy" if queue_running else "warning",
        "description": "Service Bus long-running-tasks consumer",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": {
            "queue_name": queue_status.get("queue_name", "N/A"),
            "running": queue_running,
            "messages_processed": queue_status.get("messages_processed", 0),
            "started_at": queue_status.get("started_at"),
            "last_poll_time": queue_status.get("last_poll_time"),
            "last_error": queue_status.get("last_error"),
            "shutdown_signaled": queue_status.get("shutdown_signaled", False),
            "uses_shared_shutdown": queue_status.get("uses_shared_shutdown", True),
        }
    }

    # Authentication tokens component
    pg_token = token_status.get("postgres", {})
    storage_token = token_status.get("storage", {})
    tokens_healthy = pg_token.get("has_token", False)
    components["auth_tokens"] = {
        "status": "healthy" if tokens_healthy else "unhealthy",
        "description": "OAuth tokens for PostgreSQL and Storage",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": {
            "postgres": {
                "has_token": pg_token.get("has_token", False),
                "ttl_minutes": pg_token.get("ttl_minutes"),
            },
            "storage": {
                "has_token": storage_token.get("has_token", False),
            },
            "token_refresh_worker": {
                "running": token_refresh_status.get("running", False),
                "refresh_count": token_refresh_status.get("refresh_count", 0),
                "last_refresh": token_refresh_status.get("last_refresh"),
            },
        }
    }

    # Connection pool component
    pool_has_error = "error" in pool_stats
    components["connection_pool"] = {
        "status": "healthy" if not pool_has_error else "warning",
        "description": "PostgreSQL connection pool (psycopg)",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": pool_stats,
    }

    # Lifecycle component (graceful shutdown status)
    lifecycle_status = worker_lifecycle.get_status()
    is_shutting_down = lifecycle_status.get("shutdown_initiated", False)
    components["lifecycle"] = {
        "status": "warning" if is_shutting_down else "healthy",
        "description": "Graceful shutdown and signal handling",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": lifecycle_status,
    }

    # GDAL Configuration component
    gdal_config = {}
    try:
        from osgeo import gdal
        gdal_config = {
            "version": gdal.__version__,
            "cpl_tmpdir": os.environ.get("CPL_TMPDIR", "default"),
            "gdal_data": os.environ.get("GDAL_DATA", "default"),
            "proj_lib": os.environ.get("PROJ_LIB", "default"),
        }
        gdal_status = "healthy"
    except Exception as e:
        gdal_config = {"error": str(e)}
        gdal_status = "unhealthy"

    components["gdal"] = {
        "status": gdal_status,
        "description": "GDAL geospatial library configuration",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": gdal_config,
    }

    # =========================================================================
    # SHARED INFRASTRUCTURE COMPONENTS (accessed by both apps)
    # =========================================================================

    # Database component
    db_connected = db_status.get("connected", False)
    components["database"] = {
        "status": "healthy" if db_connected else "unhealthy",
        "description": "PostgreSQL connection",
        "checked_at": timestamp.isoformat(),
        "_source": "function_app",  # Shared but owned by Function App
        "details": {
            "host": config.database.host,
            "database": db_status.get("database", config.database.database),
            "user": db_status.get("user", "N/A"),
            "version": db_status.get("version", "N/A"),
            "managed_identity": config.database.use_managed_identity,
            "error": db_status.get("error") if not db_connected else None,
        }
    }

    # Storage component
    storage_connected = storage_status.get("connected", False)
    components["storage_containers"] = {
        "status": "healthy" if storage_connected else "unhealthy",
        "description": "Azure Blob Storage (Silver zone)",
        "checked_at": timestamp.isoformat(),
        "_source": "function_app",  # Shared but owned by Function App
        "details": {
            "account": storage_status.get("account", config.storage.silver.account_name),
            "containers_accessible": storage_status.get("containers_accessible", False),
            "error": storage_status.get("error") if not storage_connected else None,
        }
    }

    # Service Bus component (shared queue infrastructure)
    components["service_bus"] = {
        "status": "healthy" if queue_running else "warning",
        "description": "Azure Service Bus queues",
        "checked_at": timestamp.isoformat(),
        "_source": "function_app",  # Shared but owned by Function App
        "details": {
            "namespace": config.queues.namespace,
            "long_running_queue": queue_status.get("queue_name", "N/A"),
            "worker_connected": queue_running,
        }
    }

    # =========================================================================
    # ADDITIONAL COMPONENTS (for health.js COMPONENT_MAPPING compatibility)
    # These are marked as disabled/N/A for Docker Worker context
    # =========================================================================

    # Jobs component (expected by comp-orchestrator)
    components["jobs"] = {
        "status": "disabled",
        "description": "Job orchestration (Function App only)",
        "checked_at": timestamp.isoformat(),
        "_source": "function_app",
        "details": {
            "note": "Docker Worker processes tasks, not jobs",
            "context": "docker_worker",
        }
    }

    # Imports component (expected by comp-io-worker, comp-compute-worker)
    components["imports"] = {
        "status": "healthy",
        "description": "Python dependencies loaded",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": {
            "python_version": platform.python_version(),
            "context": "docker_worker",
        }
    }

    # Pgstac component (expected by comp-output-tables)
    components["pgstac"] = {
        "status": "healthy" if db_connected else "unhealthy",
        "description": "STAC catalog (via database)",
        "checked_at": timestamp.isoformat(),
        "_source": "function_app",
        "details": {
            "note": "Accessed via shared PostgreSQL database",
            "database_connected": db_connected,
        }
    }

    # TiTiler component (expected by comp-titiler)
    titiler_url = getattr(config, 'titiler_base_url', None) or ''
    components["titiler"] = {
        "status": "disabled",
        "description": "TiTiler-pgstac (external service)",
        "checked_at": timestamp.isoformat(),
        "_source": "function_app",
        "details": {
            "url": titiler_url,
            "note": "External raster tile service",
        }
    }

    # OGC Features component (expected by comp-ogc-features)
    components["ogc_features"] = {
        "status": "disabled",
        "description": "OGC Features API (Function App only)",
        "checked_at": timestamp.isoformat(),
        "_source": "function_app",
        "details": {
            "note": "Served by Function App, not Docker Worker",
        }
    }

    # Deployment config component (expected by comp-platform-api)
    components["deployment_config"] = {
        "status": "healthy",
        "description": "Docker Worker deployment",
        "checked_at": timestamp.isoformat(),
        "_source": "docker_worker",
        "details": {
            "hostname": os.environ.get("WEBSITE_HOSTNAME", "docker-worker"),
            "container_id": os.environ.get("HOSTNAME", "unknown")[:12],
            "sku": os.environ.get("WEBSITE_SKU", "Container"),
        }
    }

    # =========================================================================
    # OVERALL STATUS
    # =========================================================================
    healthy = db_connected and not is_shutting_down
    if is_shutting_down:
        status = "unhealthy"
    elif healthy:
        status = "healthy"
    else:
        status = "unhealthy"

    # Build errors list
    errors = []
    if not db_connected:
        errors.append(f"Database: {db_status.get('error', 'Not connected')}")
    if not storage_connected:
        errors.append(f"Storage: {storage_status.get('error', 'Not connected')}")
    if is_shutting_down:
        errors.append("Worker is shutting down")
    if mount_degraded:
        errors.append("ETL mount disabled - degraded state")

    # Environment info (for health.js renderEnvironmentInfo)
    environment = {
        "version": __version__,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "debug_mode": os.environ.get("DEBUG_MODE", "false").lower() == "true",
        "hostname": os.environ.get("WEBSITE_HOSTNAME", os.environ.get("HOSTNAME", "docker-worker")),
    }

    response = {
        "status": status,
        "timestamp": timestamp.isoformat(),
        "errors": errors,
        "environment": environment,
        "components": components,
        # Legacy fields for backward compatibility
        "version": __version__,
        "lifecycle": lifecycle_status,
        "tokens": token_status,
        "connectivity": {
            "database": db_status,
            "storage": storage_status,
        },
        "background_workers": {
            "token_refresh": token_refresh_status,
            "queue_worker": queue_status,
        },
        "connection_pool": pool_stats,
        "runtime": {
            "hardware": hardware,
            "instance": instance,
            "process": process_info,
            "memory": memory_stats,
            "capacity": capacity,
        },
    }

    # Return 503 if unhealthy OR shutting down (prevents new traffic during shutdown)
    if not healthy or is_shutting_down:
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


@app.get("/test/mount")
def test_mount():
    """
    Test Azure Files mount at /mounts/etl-temp.

    Verifies:
    1. Mount path exists
    2. Mount is writable (creates/deletes test file)
    3. Returns disk space available
    4. GDAL can use mount for temp files (CPL_TMPDIR)
    5. Rasterio can create/read GeoTIFF on mount

    Returns:
        Mount status, disk space, and GDAL compatibility info
    """
    import shutil
    import uuid

    mount_path = "/mounts/etl-temp"
    test_id = uuid.uuid4().hex[:8]
    test_file = f"{mount_path}/.mount-test-{test_id}"
    timestamp = datetime.now(timezone.utc).isoformat()

    result = {
        "timestamp": timestamp,
        "mount_path": mount_path,
        "exists": False,
        "writable": False,
        "disk_space": None,
        "gdal_test": None,
        "error": None,
    }

    try:
        # Check if mount exists
        if os.path.exists(mount_path):
            result["exists"] = True
            result["is_directory"] = os.path.isdir(mount_path)

            # Check disk space
            try:
                usage = shutil.disk_usage(mount_path)
                result["disk_space"] = {
                    "total_gb": round(usage.total / 1e9, 2),
                    "used_gb": round(usage.used / 1e9, 2),
                    "free_gb": round(usage.free / 1e9, 2),
                    "percent_used": round((usage.used / usage.total) * 100, 1),
                }
            except Exception as e:
                result["disk_space"] = {"error": str(e)}

            # Test write capability
            try:
                with open(test_file, "w") as f:
                    f.write(f"mount test {timestamp}")
                os.remove(test_file)
                result["writable"] = True
            except Exception as e:
                result["writable"] = False
                result["write_error"] = str(e)

            # List files (up to 10)
            try:
                files = os.listdir(mount_path)
                result["files_count"] = len(files)
                result["files_sample"] = files[:10] if files else []
            except Exception as e:
                result["files_error"] = str(e)

            # GDAL/Rasterio test - create a small GeoTIFF on the mount
            result["gdal_test"] = test_gdal_on_mount(mount_path, test_id)

        else:
            result["error"] = f"Mount path does not exist: {mount_path}"

    except Exception as e:
        result["error"] = str(e)

    # Overall status
    gdal_ok = result.get("gdal_test", {}).get("success", False)
    result["status"] = "ok" if (result["exists"] and result["writable"] and gdal_ok) else "error"
    return result


def test_gdal_on_mount(mount_path: str, test_id: str) -> dict:
    """
    Test GDAL/Rasterio can use the mount for temp file operations.

    Creates a small test GeoTIFF, verifies it can be read back,
    and tests CPL_TMPDIR configuration.
    """
    import numpy as np

    gdal_result = {
        "success": False,
        "gdal_version": None,
        "rasterio_version": None,
        "cpl_tmpdir_set": False,
        "tiff_write": False,
        "tiff_read": False,
        "tiff_size_bytes": None,
        "error": None,
    }

    test_tiff = f"{mount_path}/.gdal-test-{test_id}.tif"

    try:
        from osgeo import gdal
        import rasterio
        from rasterio.transform import from_bounds

        gdal_result["gdal_version"] = gdal.__version__
        gdal_result["rasterio_version"] = rasterio.__version__

        # Set CPL_TMPDIR to use mount for GDAL temp files
        original_tmpdir = os.environ.get("CPL_TMPDIR")
        os.environ["CPL_TMPDIR"] = mount_path
        gdal.SetConfigOption("CPL_TMPDIR", mount_path)
        gdal_result["cpl_tmpdir_set"] = True
        gdal_result["cpl_tmpdir_value"] = mount_path

        # Create a small test raster (100x100, 3 bands, uint8)
        width, height = 100, 100
        data = np.random.randint(0, 255, (3, height, width), dtype=np.uint8)
        transform = from_bounds(-180, -90, 180, 90, width, height)

        # Write GeoTIFF using rasterio
        with rasterio.open(
            test_tiff,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=3,
            dtype="uint8",
            crs="EPSG:4326",
            transform=transform,
            compress="deflate",
        ) as dst:
            dst.write(data)

        gdal_result["tiff_write"] = True
        gdal_result["tiff_size_bytes"] = os.path.getsize(test_tiff)

        # Read it back to verify
        with rasterio.open(test_tiff) as src:
            read_data = src.read()
            gdal_result["tiff_read"] = True
            gdal_result["tiff_shape"] = list(read_data.shape)
            gdal_result["tiff_crs"] = str(src.crs)

        # Verify data matches
        if np.array_equal(data, read_data):
            gdal_result["data_integrity"] = True
        else:
            gdal_result["data_integrity"] = False

        gdal_result["success"] = True

    except Exception as e:
        gdal_result["error"] = str(e)

    finally:
        # Cleanup test file
        try:
            if os.path.exists(test_tiff):
                os.remove(test_tiff)
                gdal_result["cleanup"] = True
        except Exception as cleanup_error:
            gdal_result["cleanup_error"] = str(cleanup_error)

        # Restore original CPL_TMPDIR
        if original_tmpdir:
            os.environ["CPL_TMPDIR"] = original_tmpdir
            gdal.SetConfigOption("CPL_TMPDIR", original_tmpdir)
        else:
            os.environ.pop("CPL_TMPDIR", None)
            gdal.SetConfigOption("CPL_TMPDIR", None)

    return gdal_result


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
    logger.info("  - Queue polling (container-tasks)")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=port)
