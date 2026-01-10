# ============================================================================
# SERVICE METRICS BLOB LOGGER
# ============================================================================
# STATUS: Infrastructure - Blob storage persistence for service latency metrics
# PURPOSE: Dump service metrics to blob storage as JSON for QA debugging
# LAST_REVIEWED: 10 JAN 2026
# EXPORTS: MetricsBlobLogger, get_metrics_logger, flush_metrics
# DEPENDENCIES: azure.storage.blob, config
# ============================================================================
"""
Service Metrics Blob Logger.

Persists service latency metrics to Azure Blob Storage as JSON files for
debugging in opaque QA environments. Designed to be lightweight and not
impact request performance.

Architecture:
    - Metrics buffered in memory (thread-safe deque)
    - Background flush every FLUSH_INTERVAL_SECONDS or BUFFER_SIZE records
    - JSON Lines format (.jsonl) for easy parsing
    - Files named: metrics/{date}/{instance_id}/{timestamp}.jsonl

Environment Variables:
    METRICS_DEBUG_MODE: Must be true to enable (default: false)
    METRICS_BLOB_CONTAINER: Container name (default: "metrics")
    METRICS_FLUSH_INTERVAL: Seconds between flushes (default: 60)
    METRICS_BUFFER_SIZE: Max records before flush (default: 100)

Usage:
    from infrastructure.metrics_blob_logger import log_metric, flush_metrics

    # Automatic via @track_latency decorator (when enabled)

    # Manual metric logging
    log_metric("custom.operation", 150.5, {"custom_field": "value"})

    # Force flush (e.g., on shutdown)
    flush_metrics()

Blob Structure:
    metrics/
      2026-01-10/
        abc123def456/
          20260110T143052Z.jsonl
          20260110T144152Z.jsonl

JSON Lines Format (one JSON object per line):
    {"ts": "2026-01-10T14:30:52Z", "op": "ogc.query_features", "ms": 145.2, "status": "success", ...}
    {"ts": "2026-01-10T14:30:53Z", "op": "ogc.get_collection", "ms": 23.1, "status": "success", ...}
"""

import json
import os
import threading
import time
import atexit
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Deque
from dataclasses import dataclass, field, asdict

# ============================================================================
# CONFIGURATION
# ============================================================================

# Flush settings
DEFAULT_FLUSH_INTERVAL = 60  # seconds
DEFAULT_BUFFER_SIZE = 100  # records
DEFAULT_CONTAINER = "applogs"

# Module-level state
_logger_instance: Optional["MetricsBlobLogger"] = None
_logger_lock = threading.Lock()


# ============================================================================
# METRIC RECORD
# ============================================================================

@dataclass
class MetricRecord:
    """Single metric record for blob storage."""
    ts: str  # ISO timestamp
    op: str  # Operation name
    ms: float  # Duration in milliseconds
    status: str  # success/error/timeout
    layer: str = "service"  # service/database/section
    slow: bool = False
    instance_id: str = ""
    error: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_json_line(self) -> str:
        """Convert to JSON line (compact, no newlines in output)."""
        data = {
            "ts": self.ts,
            "op": self.op,
            "ms": round(self.ms, 2),
            "status": self.status,
            "layer": self.layer,
        }
        if self.slow:
            data["slow"] = True
        if self.instance_id:
            data["instance"] = self.instance_id[:16]  # Truncate for readability
        if self.error:
            data["error"] = self.error[:200]  # Truncate long errors
        if self.extra:
            data.update(self.extra)
        return json.dumps(data, separators=(',', ':'))


# ============================================================================
# METRICS BLOB LOGGER
# ============================================================================

class MetricsBlobLogger:
    """
    Buffered blob logger for service metrics.

    Thread-safe, background flushing, conditional on METRICS_DEBUG_MODE.
    """

    def __init__(self):
        """Initialize logger with configuration from environment."""
        self.enabled = self._check_enabled()
        self.container_name = os.environ.get("METRICS_BLOB_CONTAINER", DEFAULT_CONTAINER)
        self.flush_interval = int(os.environ.get("METRICS_FLUSH_INTERVAL", DEFAULT_FLUSH_INTERVAL))
        self.buffer_size = int(os.environ.get("METRICS_BUFFER_SIZE", DEFAULT_BUFFER_SIZE))

        # Thread-safe buffer
        self.buffer: Deque[MetricRecord] = deque(maxlen=self.buffer_size * 2)  # 2x to avoid drops
        self.buffer_lock = threading.Lock()

        # Instance identification
        self.instance_id = os.environ.get("WEBSITE_INSTANCE_ID", "local")[:32]

        # Background flush thread
        self._flush_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Blob client (lazy init)
        self._blob_service_client = None

        # Stats
        self.records_logged = 0
        self.records_flushed = 0
        self.flush_errors = 0

        if self.enabled:
            self._start_background_flush()
            atexit.register(self.shutdown)

    def _check_enabled(self) -> bool:
        """Check if metrics blob logging is enabled."""
        # Requires METRICS_DEBUG_MODE=true
        debug_mode = os.environ.get("METRICS_DEBUG_MODE", "false").lower() == "true"
        return debug_mode

    def _get_blob_client(self):
        """Get or create blob service client (lazy initialization)."""
        if self._blob_service_client is None:
            try:
                from azure.storage.blob import BlobServiceClient
                from azure.identity import DefaultAzureCredential

                # Get storage account from config
                storage_account = os.environ.get("SILVER_STORAGE_ACCOUNT")
                if not storage_account:
                    return None

                account_url = f"https://{storage_account}.blob.core.windows.net"

                # Try managed identity first, fall back to connection string
                try:
                    credential = DefaultAzureCredential()
                    self._blob_service_client = BlobServiceClient(
                        account_url=account_url,
                        credential=credential
                    )
                except Exception:
                    # Fall back to storage key if available
                    storage_key = os.environ.get("AZURE_STORAGE_KEY")
                    if storage_key:
                        conn_str = f"DefaultEndpointsProtocol=https;AccountName={storage_account};AccountKey={storage_key};EndpointSuffix=core.windows.net"
                        self._blob_service_client = BlobServiceClient.from_connection_string(conn_str)
                    else:
                        return None

            except ImportError:
                return None
            except Exception:
                return None

        return self._blob_service_client

    def _start_background_flush(self):
        """Start background thread for periodic flushing."""
        if self._flush_thread is not None:
            return

        def flush_loop():
            while not self._stop_event.wait(timeout=self.flush_interval):
                try:
                    self._flush_buffer()
                except Exception:
                    self.flush_errors += 1

        self._flush_thread = threading.Thread(target=flush_loop, daemon=True)
        self._flush_thread.start()

    def log(
        self,
        operation: str,
        duration_ms: float,
        status: str = "success",
        layer: str = "service",
        slow: bool = False,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ):
        """
        Log a metric record to the buffer.

        Args:
            operation: Operation name (e.g., "ogc.query_features")
            duration_ms: Duration in milliseconds
            status: "success", "error", "timeout"
            layer: "service", "database", "section"
            slow: Whether this was a slow operation
            error: Error message if status is error
            extra: Additional context fields
        """
        if not self.enabled:
            return

        record = MetricRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            op=operation,
            ms=duration_ms,
            status=status,
            layer=layer,
            slow=slow,
            instance_id=self.instance_id,
            error=error,
            extra=extra or {}
        )

        with self.buffer_lock:
            self.buffer.append(record)
            self.records_logged += 1

            # Flush if buffer is full
            if len(self.buffer) >= self.buffer_size:
                self._flush_buffer_locked()

    def _flush_buffer(self):
        """Flush buffer to blob storage (acquires lock)."""
        with self.buffer_lock:
            self._flush_buffer_locked()

    def _flush_buffer_locked(self):
        """Flush buffer to blob storage (must hold lock)."""
        if not self.buffer:
            return

        # Get all records from buffer
        records = list(self.buffer)
        self.buffer.clear()

        # Build JSON Lines content
        lines = [r.to_json_line() for r in records]
        content = "\n".join(lines) + "\n"

        # Generate blob name
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        timestamp_str = now.strftime("%Y%m%dT%H%M%SZ")
        blob_name = f"service-metrics/{date_str}/{self.instance_id[:16]}/{timestamp_str}.jsonl"

        # Upload to blob
        try:
            client = self._get_blob_client()
            if client:
                container_client = client.get_container_client(self.container_name)

                # Ensure container exists (ignore if already exists)
                try:
                    container_client.create_container()
                except Exception:
                    pass  # Container already exists

                blob_client = container_client.get_blob_client(blob_name)
                blob_client.upload_blob(content, overwrite=True)
                self.records_flushed += len(records)
        except Exception as e:
            self.flush_errors += 1
            # Re-add records to buffer on failure (best effort)
            for record in records[:self.buffer_size]:
                self.buffer.appendleft(record)

    def flush(self):
        """Force flush buffer to blob storage."""
        if not self.enabled:
            return {"enabled": False}

        self._flush_buffer()
        return {
            "flushed": True,
            "records_logged": self.records_logged,
            "records_flushed": self.records_flushed,
            "flush_errors": self.flush_errors,
            "buffer_remaining": len(self.buffer)
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get logger statistics."""
        return {
            "enabled": self.enabled,
            "records_logged": self.records_logged,
            "records_flushed": self.records_flushed,
            "flush_errors": self.flush_errors,
            "buffer_size": len(self.buffer),
            "instance_id": self.instance_id[:16],
            "container": self.container_name,
            "flush_interval": self.flush_interval,
        }

    def ensure_container_exists(self) -> bool:
        """
        Ensure the metrics container exists in blob storage.

        Call this during startup to avoid container creation delays during
        the first metrics flush.

        Returns:
            bool: True if container exists or was created, False on error
        """
        if not self.enabled:
            return False

        try:
            client = self._get_blob_client()
            if not client:
                return False

            container_client = client.get_container_client(self.container_name)

            # Check if exists, create if not
            if not container_client.exists():
                container_client.create_container()

            return True

        except Exception:
            return False

    def shutdown(self):
        """Shutdown logger and flush remaining records."""
        if not self.enabled:
            return

        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)

        # Final flush
        try:
            self._flush_buffer()
        except Exception:
            pass


# ============================================================================
# MODULE-LEVEL FUNCTIONS
# ============================================================================

def get_metrics_logger() -> MetricsBlobLogger:
    """Get singleton metrics logger instance."""
    global _logger_instance
    if _logger_instance is None:
        with _logger_lock:
            if _logger_instance is None:
                _logger_instance = MetricsBlobLogger()
    return _logger_instance


def log_metric(
    operation: str,
    duration_ms: float,
    status: str = "success",
    layer: str = "service",
    slow: bool = False,
    error: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None
):
    """
    Log a metric record (convenience function).

    Only logs if METRICS_DEBUG_MODE=true.
    """
    get_metrics_logger().log(
        operation=operation,
        duration_ms=duration_ms,
        status=status,
        layer=layer,
        slow=slow,
        error=error,
        extra=extra
    )


def flush_metrics() -> Dict[str, Any]:
    """Force flush metrics to blob storage."""
    return get_metrics_logger().flush()


def get_metrics_stats() -> Dict[str, Any]:
    """Get metrics logger statistics."""
    return get_metrics_logger().get_stats()


def init_metrics_container() -> bool:
    """
    Initialize metrics blob container at startup.

    Call this during app startup to ensure the container exists.
    Only does work if METRICS_DEBUG_MODE=true.

    Returns:
        bool: True if container exists/created, False if disabled or error
    """
    return get_metrics_logger().ensure_container_exists()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "MetricsBlobLogger",
    "get_metrics_logger",
    "log_metric",
    "flush_metrics",
    "get_metrics_stats",
    "init_metrics_container",
    "MetricRecord",
]
