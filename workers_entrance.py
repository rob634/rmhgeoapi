#!/usr/bin/env python3
# ============================================================================
# CLAUDE CONTEXT - WORKERS ENTRANCE (Docker HTTP + Health Endpoints)
# ============================================================================
# STATUS: Core Component - HTTP API for Docker container health and operations
# PURPOSE: Health checks, auth validation, and handler execution for Docker
# LAST_REVIEWED: 10 JAN 2026
# ============================================================================
"""
Workers Entrance - Docker Container HTTP API.

Provides HTTP endpoints for:
    - Kubernetes-style health checks (livez, readyz, health)
    - Database connectivity validation
    - Storage connectivity validation
    - Direct handler execution (for testing)

Background Services:
    - Token refresh thread (PostgreSQL + Storage OAuth)
    - Queue polling thread (optional, for task processing)

Health Check Endpoints:
    /livez  - Liveness probe (is the process running?)
    /readyz - Readiness probe (can we serve traffic?)
    /health - Detailed health (token status, connectivity)

Usage:
    # Start the server
    uvicorn workers_entrance:app --host 0.0.0.0 --port 80

    # Test endpoints
    curl http://localhost/livez
    curl http://localhost/readyz
    curl http://localhost/health
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
# LOGGING SETUP
# ============================================================================

def configure_docker_logging():
    """Configure logging for Docker environment."""
    import logging

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

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

import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
    print("WORKERS ENTRANCE - STARTING", flush=True)
    print("=" * 60, flush=True)

    # Initialize authentication (acquire tokens, configure GDAL)
    logger.info("Initializing Docker authentication...")
    auth_status = initialize_docker_auth()
    logger.info(f"Auth initialization: {auth_status}")

    # Start background token refresh
    token_refresh_worker.start()

    yield

    # Shutdown
    print("WORKERS ENTRANCE - SHUTTING DOWN", flush=True)
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
    - Token status (TTL, expiry)
    - Database connectivity
    - Storage connectivity
    - Background worker status

    Returns:
        Detailed health status
    """
    from infrastructure.auth import get_token_status
    from config import get_config

    config = get_config()

    # Get token status
    token_status = get_token_status()

    # Test connectivity
    db_status = test_database_connectivity()
    storage_status = test_storage_connectivity()

    # Overall health
    healthy = db_status.get("connected", False)

    response = {
        "status": "healthy" if healthy else "unhealthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "config": {
            "database_host": config.database.host,
            "storage_account": config.storage.silver.account_name,
            "managed_identity": config.database.use_managed_identity,
        },
        "tokens": token_status,
        "connectivity": {
            "database": db_status,
            "storage": storage_status,
        },
        "background_workers": {
            "token_refresh": token_refresh_worker.get_status(),
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
    logger.info("Workers Entrance - Docker Container API")
    logger.info(f"Port: {port}")
    logger.info("=" * 60)
    logger.info("Health Endpoints:")
    logger.info("  GET  /livez       - Liveness probe")
    logger.info("  GET  /readyz      - Readiness probe")
    logger.info("  GET  /health      - Detailed health check")
    logger.info("Auth Endpoints:")
    logger.info("  GET  /auth/status - Token status")
    logger.info("  POST /auth/refresh - Force token refresh")
    logger.info("Test Endpoints:")
    logger.info("  GET  /test/database - Test DB connectivity")
    logger.info("  GET  /test/storage  - Test storage connectivity")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=port)
