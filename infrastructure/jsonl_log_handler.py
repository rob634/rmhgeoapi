# ============================================================================
# JSONL LOG HANDLER
# ============================================================================
# STATUS: Infrastructure - JSONL blob storage handler for structured logs
# PURPOSE: Export structured logs to Azure Blob Storage as JSONL files
# CREATED: 11 JAN 2026
# EPIC: E7 Pipeline Infrastructure - F7.12.F JSONL Log Dump System
# EXPORTS: JSONLBlobHandler, get_log_handler, flush_logs
# DEPENDENCIES: azure.storage.blob, config.observability
# ============================================================================
"""
JSONL Log Handler.

Exports Python logging records to Azure Blob Storage as JSON Lines files.
Provides granular control over what gets exported based on log level and
component type.

Architecture:
    - Extends logging.Handler for seamless integration
    - Buffers logs in memory (thread-safe deque)
    - Background flush every FLUSH_INTERVAL or BUFFER_SIZE records
    - JSON Lines format (.jsonl) for easy parsing
    - Files named: logs/{mode}/{date}/{instance_id}/{timestamp}.jsonl

Environment Variables (11 JAN 2026 - F7.12.F):
    OBSERVABILITY_MODE: Must be true to enable (default: false)
    VERBOSE_LOG_DUMP: When true (with OBSERVABILITY_MODE), dumps ALL logs
                      When false, only dumps janitor/timer logs + WARNING+
    JSONL_LOG_CONTAINER: Container name (default: "applogs")
    JSONL_FLUSH_INTERVAL: Seconds between flushes (default: 60)
    JSONL_BUFFER_SIZE: Max records before flush (default: 100)

Blob Structure (flat - no nested date/instance folders):
    applogs/
      logs/
        default/           # WARNING+ from all, DEBUG+ from janitor/timer
          20260112T143052Z_instance123.jsonl
        verbose/           # ALL logs (when VERBOSE_LOG_DUMP=true)
          20260112T143052Z_instance123.jsonl

JSON Lines Format:
    {"ts": "2026-01-12T14:30:52Z", "level": "WARNING", "logger": "service.StacCatalog", ...}
"""

import json
import logging
import os
import threading
import time
import atexit
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Deque, Set
from dataclasses import dataclass, field


# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_FLUSH_INTERVAL = 60  # seconds
DEFAULT_BUFFER_SIZE = 100  # records
DEFAULT_CONTAINER = "applogs"

# Components that get DEBUG+ logging even in non-verbose mode
JANITOR_TIMER_COMPONENTS: Set[str] = {
    # Timer handlers
    "trigger.TaskWatchdog",
    "trigger.JobHealth",
    "trigger.OrphanDetector",
    "trigger.GeoOrphanCheck",
    "trigger.MetadataConsistency",
    "trigger.SystemSnapshot",
    "trigger.LogCleanup",
    # Janitor services
    "service.janitor_service",
    "service.TaskWatchdog",
    "service.JobHealthChecker",
    "service.OrphanDetector",
    "service.GeoOrphanDetector",
    # Timer base
    "trigger.UnnamedTimer",
}

# Module-level state
_handler_instance: Optional["JSONLBlobHandler"] = None
_handler_lock = threading.Lock()


# ============================================================================
# LOG RECORD (Unified Schema)
# ============================================================================

@dataclass
class LogRecord:
    """
    Single log record for blob storage.

    Unified schema for logger/metrics/diagnostics consistency.
    See TODO.md F7.12.F for schema design decisions.
    """
    ts: str  # ISO timestamp
    level: str  # DEBUG/INFO/WARNING/ERROR/CRITICAL
    logger: str  # Logger name (e.g., "service.StacCatalog")
    message: str  # Log message
    module: str = ""  # Python module
    function: str = ""  # Python function
    line: int = 0  # Line number

    # Global context (from F7.12.A)
    app_name: str = ""
    app_instance: str = ""
    environment: str = ""

    # Correlation context
    component_type: str = ""
    component_name: str = ""
    job_id: Optional[str] = None
    task_id: Optional[str] = None
    stage: Optional[int] = None
    correlation_id: Optional[str] = None

    # Error info
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None

    # Custom dimensions
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_json_line(self) -> str:
        """Convert to JSON line (compact, no newlines in output)."""
        data = {
            "ts": self.ts,
            "level": self.level,
            "logger": self.logger,
            "message": self.message[:2000],  # Truncate long messages
        }

        # Add optional fields only if set
        if self.module:
            data["module"] = self.module
        if self.function:
            data["function"] = self.function
        if self.line:
            data["line"] = self.line

        # Global context
        if self.app_name:
            data["app_name"] = self.app_name
        if self.app_instance:
            data["app_instance"] = self.app_instance[:16]
        if self.environment:
            data["environment"] = self.environment

        # Component context
        if self.component_type:
            data["component_type"] = self.component_type
        if self.component_name:
            data["component_name"] = self.component_name

        # Correlation
        if self.job_id:
            data["job_id"] = self.job_id
        if self.task_id:
            data["task_id"] = self.task_id
        if self.stage is not None:
            data["stage"] = self.stage
        if self.correlation_id:
            data["correlation_id"] = self.correlation_id

        # Error info
        if self.error_type:
            data["error_type"] = self.error_type
        if self.error_message:
            data["error_message"] = self.error_message[:500]
        if self.traceback:
            data["traceback"] = self.traceback[:2000]

        # Custom dimensions
        if self.custom:
            data["custom"] = self.custom

        return json.dumps(data, separators=(',', ':'), default=str)


# ============================================================================
# JSONL BLOB HANDLER
# ============================================================================

class JSONLBlobHandler(logging.Handler):
    """
    Logging handler that exports logs to Azure Blob Storage as JSONL.

    Provides granular control:
    - OBSERVABILITY_MODE=true: Janitor/timer DEBUG+ logs, WARNING+ from everywhere else
    - OBSERVABILITY_MODE=true + VERBOSE_LOG_DUMP=true: ALL logs including DEBUG

    Thread-safe with background flushing.
    """

    def __init__(self, level: int = logging.DEBUG):
        """
        Initialize handler with configuration from environment.

        Args:
            level: Minimum log level to capture (default: DEBUG)
        """
        super().__init__(level=level)

        # Configuration from environment
        self.observability_enabled = self._check_observability_enabled()
        self.verbose_mode = self._check_verbose_mode()
        self.container_name = os.environ.get("JSONL_LOG_CONTAINER", DEFAULT_CONTAINER)
        self.flush_interval = int(os.environ.get("JSONL_FLUSH_INTERVAL", DEFAULT_FLUSH_INTERVAL))
        self.buffer_size = int(os.environ.get("JSONL_BUFFER_SIZE", DEFAULT_BUFFER_SIZE))

        # Thread-safe buffers (separate for default and verbose)
        self.default_buffer: Deque[LogRecord] = deque(maxlen=self.buffer_size * 2)
        self.verbose_buffer: Deque[LogRecord] = deque(maxlen=self.buffer_size * 2)
        self.buffer_lock = threading.Lock()

        # Instance identification
        self.instance_id = os.environ.get("WEBSITE_INSTANCE_ID", "local")[:32]
        self.app_name = os.environ.get("APP_NAME", "unknown")
        self.environment = os.environ.get("ENVIRONMENT", "dev")

        # Background flush thread
        self._flush_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Blob client (lazy init)
        self._blob_service_client = None

        # Stats
        self.records_logged = 0
        self.records_flushed = 0
        self.flush_errors = 0

        if self.observability_enabled:
            self._start_background_flush()
            atexit.register(self.shutdown)

    def _check_observability_enabled(self) -> bool:
        """Check if observability mode is enabled."""
        for var in ("OBSERVABILITY_MODE", "METRICS_DEBUG_MODE", "DEBUG_MODE"):
            val = os.environ.get(var, "").lower()
            if val in ("true", "1", "yes"):
                return True
        return False

    def _check_verbose_mode(self) -> bool:
        """Check if verbose log dump is enabled."""
        val = os.environ.get("VERBOSE_LOG_DUMP", "").lower()
        return val in ("true", "1", "yes")

    def _should_log_to_default(self, record: logging.LogRecord) -> bool:
        """
        Determine if record should go to default (non-verbose) output.

        Rules:
        - Janitor/timer components: Always include (DEBUG+)
        - Other components: Only WARNING+
        """
        # Check if this is a janitor/timer component
        logger_name = record.name
        for component in JANITOR_TIMER_COMPONENTS:
            if logger_name.startswith(component) or component in logger_name:
                return True

        # For other components, only WARNING and above
        return record.levelno >= logging.WARNING

    def _get_blob_client(self):
        """Get or create blob service client (lazy initialization)."""
        if self._blob_service_client is None:
            try:
                from azure.storage.blob import BlobServiceClient
                from azure.identity import DefaultAzureCredential

                storage_account = os.environ.get("SILVER_STORAGE_ACCOUNT")
                if not storage_account:
                    return None

                account_url = f"https://{storage_account}.blob.core.windows.net"

                try:
                    credential = DefaultAzureCredential()
                    self._blob_service_client = BlobServiceClient(
                        account_url=account_url,
                        credential=credential
                    )
                except Exception:
                    storage_key = os.environ.get("AZURE_STORAGE_KEY")
                    if storage_key:
                        conn_str = (
                            f"DefaultEndpointsProtocol=https;"
                            f"AccountName={storage_account};"
                            f"AccountKey={storage_key};"
                            f"EndpointSuffix=core.windows.net"
                        )
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
                    self._flush_buffers()
                except Exception:
                    self.flush_errors += 1

        self._flush_thread = threading.Thread(
            target=flush_loop,
            daemon=True,
            name="jsonl-log-flush"
        )
        self._flush_thread.start()

    def emit(self, record: logging.LogRecord):
        """
        Emit a log record to the appropriate buffer.

        Args:
            record: Python LogRecord to process
        """
        if not self.observability_enabled:
            return

        try:
            # Build our LogRecord from Python's LogRecord
            log_record = self._convert_record(record)

            with self.buffer_lock:
                # Always add to default buffer if it meets criteria
                if self._should_log_to_default(record):
                    self.default_buffer.append(log_record)

                # Add to verbose buffer if verbose mode enabled
                if self.verbose_mode:
                    self.verbose_buffer.append(log_record)

                self.records_logged += 1

                # Flush if buffers are full
                if (len(self.default_buffer) >= self.buffer_size or
                    len(self.verbose_buffer) >= self.buffer_size):
                    self._flush_buffers_locked()

        except Exception:
            # Don't let logging failures break the application
            self.flush_errors += 1

    def _convert_record(self, record: logging.LogRecord) -> LogRecord:
        """Convert Python LogRecord to our LogRecord."""
        # Extract custom dimensions if present
        custom_dims = {}
        if hasattr(record, 'custom_dimensions'):
            custom_dims = record.custom_dimensions.copy()

        # Extract correlation info from custom dimensions
        job_id = custom_dims.pop('job_id', None)
        task_id = custom_dims.pop('task_id', None)
        stage = custom_dims.pop('stage', None)
        correlation_id = custom_dims.pop('correlation_id', None)
        component_type = custom_dims.pop('component_type', '')
        component_name = custom_dims.pop('component_name', '')
        app_name = custom_dims.pop('app_name', self.app_name)
        app_instance = custom_dims.pop('app_instance', self.instance_id[:16])
        environment = custom_dims.pop('environment', self.environment)

        # Build error info
        error_type = None
        error_message = None
        traceback_str = None

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            if exc_type:
                error_type = exc_type.__name__
            if exc_value:
                error_message = str(exc_value)
            if exc_tb:
                import traceback
                traceback_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

        return LogRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
            module=record.module,
            function=record.funcName,
            line=record.lineno,
            app_name=app_name,
            app_instance=app_instance,
            environment=environment,
            component_type=component_type,
            component_name=component_name,
            job_id=job_id,
            task_id=task_id,
            stage=stage,
            correlation_id=correlation_id,
            error_type=error_type,
            error_message=error_message,
            traceback=traceback_str,
            custom=custom_dims if custom_dims else {}
        )

    def _flush_buffers(self):
        """Flush both buffers to blob storage (acquires lock)."""
        with self.buffer_lock:
            self._flush_buffers_locked()

    def _flush_buffers_locked(self):
        """Flush both buffers to blob storage (must hold lock)."""
        # Flush default buffer
        if self.default_buffer:
            records = list(self.default_buffer)
            self.default_buffer.clear()
            self._upload_records(records, "default")

        # Flush verbose buffer
        if self.verbose_buffer:
            records = list(self.verbose_buffer)
            self.verbose_buffer.clear()
            self._upload_records(records, "verbose")

    def _upload_records(self, records: list, mode: str):
        """
        Upload records to blob storage.

        Args:
            records: List of LogRecord objects
            mode: "default" or "verbose"
        """
        if not records:
            return

        # Build JSON Lines content
        lines = [r.to_json_line() for r in records]
        content = "\n".join(lines) + "\n"

        # Generate blob name (flat structure - no nested folders)
        # Format: logs/{mode}/{timestamp}_{instance}.jsonl (sortable by date)
        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%dT%H%M%SZ")
        blob_name = f"logs/{mode}/{timestamp_str}_{self.instance_id[:16]}.jsonl"

        try:
            client = self._get_blob_client()
            if client:
                container_client = client.get_container_client(self.container_name)

                # Ensure container exists
                try:
                    container_client.create_container()
                except Exception:
                    pass  # Container already exists

                blob_client = container_client.get_blob_client(blob_name)
                blob_client.upload_blob(content, overwrite=True)
                self.records_flushed += len(records)

        except Exception:
            self.flush_errors += 1
            # Re-add records to buffer on failure (best effort, limited)
            buffer = self.default_buffer if mode == "default" else self.verbose_buffer
            for record in records[:self.buffer_size // 2]:
                buffer.appendleft(record)

    def flush(self):
        """Force flush all buffers to blob storage."""
        if not self.observability_enabled:
            return {"enabled": False}

        self._flush_buffers()
        return {
            "flushed": True,
            "records_logged": self.records_logged,
            "records_flushed": self.records_flushed,
            "flush_errors": self.flush_errors,
            "default_buffer_remaining": len(self.default_buffer),
            "verbose_buffer_remaining": len(self.verbose_buffer),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics."""
        return {
            "enabled": self.observability_enabled,
            "verbose_mode": self.verbose_mode,
            "records_logged": self.records_logged,
            "records_flushed": self.records_flushed,
            "flush_errors": self.flush_errors,
            "default_buffer_size": len(self.default_buffer),
            "verbose_buffer_size": len(self.verbose_buffer),
            "instance_id": self.instance_id[:16],
            "container": self.container_name,
            "flush_interval": self.flush_interval,
        }

    def shutdown(self):
        """Shutdown handler and flush remaining records."""
        if not self.observability_enabled:
            return

        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)

        # Final flush
        try:
            self._flush_buffers()
        except Exception:
            pass


# ============================================================================
# MODULE-LEVEL FUNCTIONS
# ============================================================================

def get_log_handler() -> JSONLBlobHandler:
    """Get singleton JSONL log handler instance."""
    global _handler_instance
    if _handler_instance is None:
        with _handler_lock:
            if _handler_instance is None:
                _handler_instance = JSONLBlobHandler()
    return _handler_instance


def flush_logs() -> Dict[str, Any]:
    """Force flush logs to blob storage."""
    return get_log_handler().flush()


def get_log_stats() -> Dict[str, Any]:
    """Get log handler statistics."""
    return get_log_handler().get_stats()


def is_jsonl_logging_enabled() -> bool:
    """Check if JSONL logging is enabled."""
    return get_log_handler().observability_enabled


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "JSONLBlobHandler",
    "LogRecord",
    "get_log_handler",
    "flush_logs",
    "get_log_stats",
    "is_jsonl_logging_enabled",
    "JANITOR_TIMER_COMPONENTS",
]
