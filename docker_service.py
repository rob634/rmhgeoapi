#!/usr/bin/env python3
# ============================================================================
# CLAUDE CONTEXT - DOCKER SERVICE (HTTP + Queue Worker)
# ============================================================================
# STATUS: Core Component - Docker container with HTTP API and queue processing
# PURPOSE: Health checks + Service Bus queue polling for long-running tasks
# LAST_REVIEWED: 11 JAN 2026
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

        configure_azure_monitor(
            connection_string=connection_string,
            # Cloud role helps identify this app in App Insights
            resource_attributes={
                "service.name": app_name,
                "service.namespace": "rmhgeoapi",
                "deployment.environment": environment,
            },
            # Enable all telemetry types
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


configure_docker_logging()

import json
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Azure Service Bus imports for queue polling
from azure.servicebus import ServiceBusClient, ServiceBusReceiver, ServiceBusReceivedMessage
from azure.servicebus.exceptions import (
    ServiceBusError,
    ServiceBusConnectionError,
    OperationTimeoutError,
)
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


# ============================================================================
# BACKGROUND TOKEN REFRESH
# ============================================================================

class TokenRefreshWorker:
    """Background worker that refreshes OAuth tokens periodically."""

    def __init__(self, interval_seconds: int = 45 * 60):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
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

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[Token Refresh] Background thread started")

    def stop(self):
        """Stop the background thread."""
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
        }


# Global instances
token_refresh_worker = TokenRefreshWorker()


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
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
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
        """Process a single message via CoreMachine."""
        from core.schema.queue import TaskQueueMessage

        start_time = time.time()
        task_id = "unknown"

        try:
            message_body = str(message)
            task_data = json.loads(message_body)
            task_message = TaskQueueMessage(**task_data)
            task_id = task_message.task_id

            logger.info(
                f"[Queue] Processing: {task_id[:16]}... "
                f"(type: {task_message.task_type}, stage: {task_message.stage})"
            )

            # Process via CoreMachine - identical to Function App
            result = self._core_machine.process_task_message(task_message)
            elapsed = time.time() - start_time

            if result.get('success'):
                logger.info(f"[Queue] Completed in {elapsed:.2f}s: {task_id[:16]}...")
                receiver.complete_message(message)
                self._messages_processed += 1

                if result.get('stage_complete'):
                    logger.info(
                        f"[Queue] Stage {task_message.stage} complete for job "
                        f"{task_message.parent_job_id[:16]}..."
                    )
                return True
            else:
                error = result.get('error', 'Unknown error')
                logger.error(f"[Queue] Failed after {elapsed:.2f}s: {error}")
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

        while not self._stop_event.is_set():
            try:
                with client.get_queue_receiver(
                    queue_name=self._queue_name,
                    max_wait_time=self.max_wait_time_seconds,
                ) as receiver:

                    self._last_poll_time = datetime.now(timezone.utc)
                    self._last_error = None

                    messages = receiver.receive_messages(
                        max_message_count=1,
                        max_wait_time=self.max_wait_time_seconds
                    )

                    if not messages:
                        continue

                    for message in messages:
                        if self._stop_event.is_set():
                            receiver.abandon_message(message)
                            break
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
        self._is_running = False
        if self._sb_client:
            try:
                self._sb_client.close()
            except Exception:
                pass
            self._sb_client = None

        logger.info("[Queue Worker] Stopped")

    def start(self):
        """Start the background worker thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[Queue Worker] Already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[Queue Worker] Background thread started")

    def stop(self):
        """Stop the background worker thread."""
        logger.info("[Queue Worker] Stopping...")
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
        }


# Global queue worker instance
queue_worker = BackgroundQueueWorker()


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

    # Initialize authentication (acquire tokens, configure GDAL)
    logger.info("Initializing Docker authentication...")
    auth_status = initialize_docker_auth()
    logger.info(f"Auth initialization: {auth_status}")

    # Start background token refresh
    token_refresh_worker.start()

    # Start background queue worker (polls long-running-tasks queue)
    queue_worker.start()

    yield

    # Shutdown
    print("DOCKER SERVICE - SHUTTING DOWN", flush=True)
    queue_worker.stop()
    token_refresh_worker.stop()


# FastAPI app
app = FastAPI(
    title="Workers Entrance",
    description="Docker Container Health and Operations API",
    version="1.0.0",
    lifespan=lifespan
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

    # Overall health
    healthy = db_status.get("connected", False)

    response = {
        "status": "healthy" if healthy else "unhealthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
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
    }

    if not healthy:
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
