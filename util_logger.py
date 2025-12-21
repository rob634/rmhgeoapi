"""
Unified Logger System.

JSON-only structured logging for Azure Functions with Application Insights.

Design Principles:
    - Strong typing with dataclasses (stdlib only)
    - Enum safety for categories
    - Component-specific loggers
    - Clean factory pattern

Exports:
    ComponentType: Enum for component types
    LogLevel: Enum for log levels
    LogContext: Logging context dataclass
    LogEvent: Log event dataclass
    LoggerFactory: Factory for creating loggers
    log_exceptions: Exception logging decorator
    get_memory_stats: Memory/CPU statistics helper
    get_runtime_environment: Runtime environment info (CPU, RAM, platform)
    log_memory_checkpoint: Resource checkpoint logger (memory, CPU, duration)
    clear_checkpoint_context: Clear checkpoint timing for a context
    monitored_gdal_operation: Context manager for GDAL ops with pulse monitoring

Dependencies:
    Standard library only (logging, enum, dataclasses, json)
    Optional: psutil (lazy import for memory tracking in debug mode)
    Optional: config (lazy import for debug mode check)
"""

from enum import Enum
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
import logging
import sys
import os
import json
import time
import traceback
from functools import wraps
from contextlib import contextmanager
import threading


# ============================================================================
# DEBUG MODE - Lazy imports for memory tracking (8 NOV 2025)
# ============================================================================

def _lazy_import_psutil():
    """
    Lazy import psutil for memory tracking.

    Returns tuple of (psutil, os) modules or (None, None) if unavailable.
    This prevents import failures if psutil is not installed.
    """
    try:
        import psutil
        return psutil, os
    except ImportError:
        return None, None


# Prime CPU tracking at module load (20 DEC 2025)
# First call to cpu_percent() always returns 0.0, so we prime it here
def _prime_cpu_tracking():
    """Prime psutil CPU tracking so subsequent calls return actual values."""
    try:
        import psutil
        # These first calls return 0.0 but prime the internal counters
        psutil.cpu_percent(interval=None)
        psutil.Process(os.getpid()).cpu_percent(interval=None)
    except Exception:
        pass  # Silently ignore - CPU tracking is optional

_prime_cpu_tracking()


# ============================================================================
# CHECKPOINT TIMING - Track duration between checkpoints (20 DEC 2025)
# ============================================================================
# Module-level dict to track checkpoint times per context (task_id, job_id, etc.)
# Key format: "{context_id}:last"
# Includes TTL-based cleanup to prevent memory leaks (20 DEC 2025)
_checkpoint_times: Dict[str, Tuple[float, float]] = {}  # key -> (timestamp, last_access_time)
_CHECKPOINT_TTL_SECONDS = 3600  # Clean up entries older than 1 hour


def get_memory_stats() -> Optional[Dict[str, float]]:
    """
    Get current process memory, CPU, and system statistics.

    Only executes if DEBUG_MODE=true in config.

    Returns:
        dict with resource stats or None if debug disabled or psutil unavailable
        {
            'process_rss_mb': float,      # Resident Set Size (actual RAM used)
            'process_vms_mb': float,      # Virtual Memory Size
            'process_cpu_percent': float, # Process CPU usage % (20 DEC 2025)
            'system_available_mb': float, # Available system memory
            'system_percent': float,      # System memory usage %
            'system_cpu_percent': float   # System CPU usage % (20 DEC 2025)
        }
    """
    # Get a logger for visibility (20 DEC 2025: stderr not visible in App Insights)
    _logger = logging.getLogger("util_logger.memory_stats")

    # Check if debug mode enabled
    try:
        from config import get_config
        config = get_config()

        if not config.debug_mode:
            return None
    except Exception as e:
        # Log warning so failure is visible in App Insights
        _logger.warning(f"⚠️ DEBUG_MODE check failed (memory stats disabled): {e}")
        return None

    # Lazy import psutil
    psutil_module, os_module = _lazy_import_psutil()
    if not psutil_module:
        _logger.warning("⚠️ DEBUG_MODE: psutil import failed - memory tracking disabled")
        return None

    try:
        process = psutil_module.Process(os_module.getpid())
        mem_info = process.memory_info()
        system_mem = psutil_module.virtual_memory()

        # CPU stats (20 DEC 2025)
        # Note: First call to cpu_percent() returns 0.0, subsequent calls return actual value
        # interval=None means non-blocking (compares to last call)
        process_cpu = process.cpu_percent(interval=None)
        system_cpu = psutil_module.cpu_percent(interval=None)

        return {
            'process_rss_mb': round(mem_info.rss / (1024**2), 1),
            'process_vms_mb': round(mem_info.vms / (1024**2), 1),
            'process_cpu_percent': round(process_cpu, 1),
            'system_available_mb': round(system_mem.available / (1024**2), 1),
            'system_percent': round(system_mem.percent, 1),
            'system_cpu_percent': round(system_cpu, 1)
        }
    except Exception as e:
        # Log warning so failure is visible in App Insights
        _logger.warning(f"⚠️ DEBUG_MODE: memory stats collection failed: {e}")
        return None


# Cached runtime environment (computed once per process)
_runtime_environment: Optional[Dict[str, Any]] = None


def get_runtime_environment() -> Optional[Dict[str, Any]]:
    """
    Get runtime environment info (CPU, RAM, platform, Azure instance).

    Cached after first call since these don't change during process lifetime.
    Only executes if DEBUG_MODE=true in config.

    Returns:
        dict with environment info or None if debug disabled:
        {
            'cpu_count': int,           # Logical CPU count
            'total_ram_gb': float,      # Total system RAM in GB
            'platform': str,            # e.g., "Linux 5.15.0"
            'python_version': str,      # e.g., "3.11.4"
            'azure_instance_id': str,   # Azure instance ID (if available)
            'azure_site_name': str,     # Function app name
            'azure_sku': str,           # App Service Plan SKU (if available)
        }
    """
    global _runtime_environment

    # Return cached result if available
    if _runtime_environment is not None:
        return _runtime_environment

    # Check if debug mode enabled
    try:
        from config import get_config
        config = get_config()
        if not config.debug_mode:
            return None
    except Exception:
        return None

    # Lazy import psutil
    psutil_module, _ = _lazy_import_psutil()
    if not psutil_module:
        return None

    try:
        import platform

        mem = psutil_module.virtual_memory()

        _runtime_environment = {
            'cpu_count': psutil_module.cpu_count() or 0,
            'total_ram_gb': round(mem.total / (1024**3), 1),
            'platform': f"{platform.system()} {platform.release()}",
            'python_version': platform.python_version(),
            'azure_instance_id': os.environ.get('WEBSITE_INSTANCE_ID', '')[:16],  # Truncate for readability
            'azure_site_name': os.environ.get('WEBSITE_SITE_NAME', ''),
            'azure_sku': os.environ.get('WEBSITE_SKU', ''),
        }

        return _runtime_environment

    except Exception:
        return None


def _cleanup_stale_checkpoints():
    """Remove checkpoint entries older than TTL to prevent memory leaks."""
    current_time = time.time()
    stale_keys = [
        key for key, (_, access_time) in _checkpoint_times.items()
        if current_time - access_time > _CHECKPOINT_TTL_SECONDS
    ]
    for key in stale_keys:
        del _checkpoint_times[key]


def log_memory_checkpoint(
    logger: logging.Logger,
    checkpoint_name: str,
    context_id: Optional[str] = None,
    **extra_fields
):
    """
    Log a resource usage checkpoint with memory, CPU, and duration tracking.

    Only logs if DEBUG_MODE=true. Otherwise, this is a no-op.
    Adds memory/CPU stats, duration since last checkpoint, and custom fields.

    Args:
        logger: Python logger instance
        checkpoint_name: Descriptive name for this checkpoint
        context_id: Optional task/job ID for tracking duration across checkpoints
                   within the same operation. If None, uses global timing.
        **extra_fields: Additional context fields (e.g., file_size_mb=815)

    Duration Tracking:
        - First checkpoint in a context: duration_since_last_ms = None
        - Subsequent checkpoints: duration_since_last_ms = time since previous checkpoint
        - Use context_id to isolate timing between concurrent operations
        - Stale entries (>1 hour) are automatically cleaned up

    Example:
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "create_cog")
        task_id = "abc123"
        log_memory_checkpoint(logger, "Start", context_id=task_id)
        # ... do work ...
        log_memory_checkpoint(logger, "After download", context_id=task_id, file_size_mb=815)
        # Output includes: duration_since_last_ms: 1234
    """
    resource_stats = get_memory_stats()
    if resource_stats:
        current_time = time.time()

        # Periodic cleanup of stale entries (every ~100 calls via simple modulo check)
        if len(_checkpoint_times) > 100:
            _cleanup_stale_checkpoints()

        # Build checkpoint key for duration tracking
        checkpoint_key = f"{context_id}:last" if context_id else "_global:last"

        # Calculate duration since last checkpoint
        duration_ms = None
        if checkpoint_key in _checkpoint_times:
            last_time, _ = _checkpoint_times[checkpoint_key]
            duration_ms = round((current_time - last_time) * 1000, 1)

        # Update checkpoint time with access time for TTL tracking
        _checkpoint_times[checkpoint_key] = (current_time, current_time)

        # Merge all fields
        all_fields = {
            **resource_stats,
            **extra_fields,
            'checkpoint': checkpoint_name,
        }

        # Add duration if we have a previous checkpoint
        if duration_ms is not None:
            all_fields['duration_since_last_ms'] = duration_ms
        else:
            # First checkpoint for this context - include runtime environment
            runtime_env = get_runtime_environment()
            if runtime_env:
                all_fields.update(runtime_env)

        # Add context_id if provided
        if context_id:
            all_fields['context_id'] = context_id[:16] if len(context_id) > 16 else context_id

        logger.info(f"📊 MEMORY CHECKPOINT: {checkpoint_name}", extra={'custom_dimensions': all_fields})


def clear_checkpoint_context(context_id: str):
    """
    Clear checkpoint timing for a specific context.

    Call this when a task/job completes to clean up timing data.
    Note: TTL-based cleanup also runs automatically, so this is optional
    but recommended for immediate cleanup.

    Args:
        context_id: The context ID used in log_memory_checkpoint calls
    """
    checkpoint_key = f"{context_id}:last"
    if checkpoint_key in _checkpoint_times:
        del _checkpoint_times[checkpoint_key]


# ============================================================================
# GDAL OPERATION MONITOR - Background pulse for long-running operations (20 DEC 2025)
# ============================================================================

@contextmanager
def monitored_gdal_operation(
    logger: logging.Logger,
    operation_name: str,
    context_id: str = None,
    pulse_interval: float = 30.0
):
    """
    Context manager for monitoring long-running GDAL operations with background pulse.

    During GDAL C library calls, Python's GIL is released, allowing background
    threads to run. This enables heartbeat logging to detect silent OOM kills -
    if the pulse stops, the last log entry shows memory state before death.

    Args:
        logger: Python logger instance
        operation_name: Descriptive name for the operation (e.g., "cog_translate")
        context_id: Optional task/job ID for checkpoint tracking
        pulse_interval: Seconds between pulse logs (default 30s)

    Usage:
        from util_logger import monitored_gdal_operation

        with monitored_gdal_operation(logger, "cog_translate", context_id=task_id):
            cog_translate(input_path, output_path, profile)

    Log Output:
        START cog_translate - logs initial memory state
        PULSE cog_translate (every 30s) - logs ongoing memory/CPU with beat count
        END cog_translate - logs final memory state and total duration

    OOM Detection:
        If process is OOM-killed, the last PULSE log in Application Insights
        shows the memory state just before death. No PULSE for >30s + degraded
        instance = likely OOM.

    Note:
        Only logs if DEBUG_MODE=true (same as log_memory_checkpoint).
    """
    stop_event = threading.Event()
    beat_count = [0]  # Use list for mutable reference in nested function
    start_time = time.time()

    def pulse_worker():
        """Background thread that emits periodic pulse logs."""
        while not stop_event.wait(timeout=pulse_interval):
            beat_count[0] += 1
            elapsed_sec = round(time.time() - start_time, 1)
            log_memory_checkpoint(
                logger,
                f"PULSE {operation_name}",
                context_id=context_id,
                beat=beat_count[0],
                elapsed_sec=elapsed_sec
            )

    # Start pulse thread (daemon=True so it dies with main process)
    pulse_thread = threading.Thread(target=pulse_worker, daemon=True, name=f"pulse-{context_id or operation_name}")
    pulse_thread.start()

    try:
        # Log start
        log_memory_checkpoint(logger, f"START {operation_name}", context_id=context_id)
        yield
        # Log successful end
        total_duration_sec = round(time.time() - start_time, 1)
        log_memory_checkpoint(
            logger,
            f"END {operation_name}",
            context_id=context_id,
            total_duration_sec=total_duration_sec,
            pulse_count=beat_count[0]
        )
    except Exception:
        # Log end with error indicator
        total_duration_sec = round(time.time() - start_time, 1)
        log_memory_checkpoint(
            logger,
            f"END {operation_name} (ERROR)",
            context_id=context_id,
            total_duration_sec=total_duration_sec,
            pulse_count=beat_count[0]
        )
        raise
    finally:
        # Stop pulse thread
        stop_event.set()
        pulse_thread.join(timeout=1.0)


def snapshot_memory_to_task(
    task_id: str,
    checkpoint_name: str,
    logger: Optional[logging.Logger] = None,
    task_repo = None,
    **extra_fields
) -> Dict[str, Any]:
    """
    Snapshot memory state and persist to task metadata (OOM evidence).

    Writes memory stats to task.metadata JSONB field so that if the process
    is OOM killed, we have evidence of last known memory state.

    Call this BEFORE heavy operations to establish baseline.

    Args:
        task_id: Task ID to update
        checkpoint_name: Name of checkpoint (e.g., "pre_cog_translate", "mid_processing")
        logger: Optional logger for checkpoint logging
        task_repo: TaskRepository instance (from infrastructure.jobs_tasks)
                   If None, only logs without persisting to DB.
        **extra_fields: Additional fields to include (e.g., file_size_mb, blob_name)

    Returns:
        Dict with memory snapshot data (also persisted to task metadata)

    Example:
        # In a handler
        from infrastructure import RepositoryFactory
        task_repo = RepositoryFactory.create_task_repository()

        snapshot = snapshot_memory_to_task(
            task_id=params['_task_id'],
            checkpoint_name="pre_cog_translate",
            logger=logger,
            task_repo=task_repo,
            input_file_mb=500
        )

        # Heavy operation - if OOM here, last snapshot is in DB
        result = cog_translate(...)

        snapshot_memory_to_task(
            task_id=params['_task_id'],
            checkpoint_name="post_cog_translate",
            logger=logger,
            task_repo=task_repo,
            output_file_mb=result['size_mb']
        )
    """
    from datetime import datetime, timezone

    # Get memory stats
    stats = get_memory_stats() or {}

    snapshot = {
        "checkpoint": checkpoint_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "process_rss_mb": stats.get('process_rss_mb'),
        "process_peak_mb": stats.get('process_peak_mb'),
        "system_available_mb": stats.get('system_available_mb'),
        "system_percent": stats.get('system_percent'),
        "cpu_percent": stats.get('system_cpu_percent'),
        **extra_fields
    }

    # Log the checkpoint
    if logger:
        log_memory_checkpoint(
            logger,
            checkpoint_name,
            context_id=task_id,
            **extra_fields
        )

    # Persist to task metadata (OOM evidence)
    if task_repo and task_id:
        try:
            # Store under memory_snapshots list in metadata
            task_repo.update_task_metadata(
                task_id,
                {
                    "memory_snapshots": [snapshot],  # Gets merged with existing
                    "last_memory_checkpoint": {
                        "name": checkpoint_name,
                        "timestamp": snapshot["timestamp"],
                        "rss_mb": snapshot["process_rss_mb"],
                        "available_mb": snapshot["system_available_mb"]
                    }
                },
                merge=True
            )
        except Exception as e:
            # Non-fatal - logging still works even if DB update fails
            if logger:
                logger.warning(f"⚠️ Failed to persist memory snapshot to task metadata: {e}")

    return snapshot


def get_peak_memory_mb() -> Optional[float]:
    """
    Get peak memory usage for current process (if available).

    Uses resource.getrusage on Unix, falls back to current RSS on Windows.

    Returns:
        Peak RSS in MB, or None if unavailable
    """
    try:
        import resource
        # maxrss is in KB on Linux, bytes on macOS
        import platform
        usage = resource.getrusage(resource.RUSAGE_SELF)
        if platform.system() == 'Darwin':
            # macOS: bytes
            return round(usage.ru_maxrss / (1024 * 1024), 1)
        else:
            # Linux: KB
            return round(usage.ru_maxrss / 1024, 1)
    except ImportError:
        # Windows - use current RSS as fallback
        try:
            import psutil
            return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        except Exception:
            return None
    except Exception:
        return None


@contextmanager
def track_peak_memory_to_task(
    task_id: str,
    task_repo,
    logger: Optional[logging.Logger] = None,
    poll_interval: float = 30.0,
    operation_name: str = "operation"
):
    """
    Track peak memory usage during long operations and persist to task metadata.

    NOT YET WIRED UP - Built for future use after testing snapshot approach.

    Uses background daemon thread to poll memory every poll_interval seconds.
    Only updates task record when a NEW maximum is observed, minimizing DB writes.
    Each DB write uses a fresh connection with fresh token (no expiration issues).

    Works during GDAL/rasterio C library calls because GIL is released.

    Args:
        task_id: Task ID to update in database
        task_repo: TaskRepository instance (from infrastructure.jobs_tasks)
        logger: Optional logger for debug output
        poll_interval: Seconds between memory polls (default 30s)
        operation_name: Name for logging (e.g., "cog_translate")

    Yields:
        Dict with live stats that can be read after the operation:
            - peak_memory_mb: Maximum RSS observed
            - poll_count: Number of polls performed
            - update_count: Number of DB updates (new max events)

    Example (NOT YET IMPLEMENTED):
        from util_logger import track_peak_memory_to_task

        with track_peak_memory_to_task(
            task_id=task_id,
            task_repo=task_repo,
            logger=logger,
            operation_name="cog_translate"
        ) as stats:
            cog_translate(...)  # GIL released, background thread tracks max

        logger.info(f"Peak memory: {stats['peak_memory_mb']} MB")

    OOM Behavior:
        If process is OOM killed, the last observed max is already persisted
        in task.metadata.peak_memory_mb - this is the OOM evidence.

    Added: 21 DEC 2025 - Built but not wired up pending testing
    """
    import psutil
    from datetime import datetime, timezone

    stop_event = threading.Event()
    max_memory_mb = [0.0]  # Mutable for closure
    poll_count = [0]
    update_count = [0]
    start_time = time.time()

    def get_current_rss_mb() -> float:
        """Get current process RSS in MB."""
        try:
            return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        except Exception:
            return 0.0

    def pulse_worker():
        """Background thread that polls memory and updates task on new max."""
        while not stop_event.wait(timeout=poll_interval):
            poll_count[0] += 1
            current_mb = get_current_rss_mb()

            # Only update if we have a new maximum
            if current_mb > max_memory_mb[0]:
                max_memory_mb[0] = current_mb
                update_count[0] += 1
                elapsed = round(time.time() - start_time, 1)

                # Log the new max
                if logger:
                    logger.debug(
                        f"📊 [PEAK_MEMORY] New max: {current_mb} MB "
                        f"(poll #{poll_count[0]}, +{elapsed}s into {operation_name})"
                    )

                # Persist to task metadata - each call gets fresh connection/token
                try:
                    task_repo.update_task_metadata(
                        task_id,
                        {
                            "peak_memory_mb": current_mb,
                            "peak_memory_at": datetime.now(timezone.utc).isoformat(),
                            "peak_memory_elapsed_sec": elapsed,
                            "peak_memory_operation": operation_name
                        },
                        merge=True
                    )
                except Exception as e:
                    # Non-fatal - log and continue polling
                    if logger:
                        logger.warning(
                            f"⚠️ Failed to persist peak memory to task (non-fatal): {e}"
                        )

    # Stats dict that caller can read after operation
    stats = {
        "peak_memory_mb": 0.0,
        "poll_count": 0,
        "update_count": 0
    }

    # Start background pulse thread
    pulse_thread = threading.Thread(
        target=pulse_worker,
        daemon=True,
        name=f"peak-mem-{task_id[:8] if task_id else 'unknown'}"
    )
    pulse_thread.start()

    if logger:
        logger.info(
            f"📊 [PEAK_MEMORY] Started tracking for {operation_name} "
            f"(poll every {poll_interval}s, task {task_id[:16]}...)"
        )

    try:
        yield stats
    finally:
        # Stop the pulse thread
        stop_event.set()
        pulse_thread.join(timeout=2.0)

        # Update stats for caller
        stats["peak_memory_mb"] = max_memory_mb[0]
        stats["poll_count"] = poll_count[0]
        stats["update_count"] = update_count[0]

        if logger:
            elapsed = round(time.time() - start_time, 1)
            logger.info(
                f"📊 [PEAK_MEMORY] Tracking complete for {operation_name}: "
                f"peak={max_memory_mb[0]} MB, polls={poll_count[0]}, "
                f"updates={update_count[0]}, duration={elapsed}s"
            )


# ============================================================================
# COMPONENT TYPES - Aligned with pyramid architecture
# ============================================================================

class ComponentType(Enum):
    """
    Component types aligned with pyramid architecture layers.

    Each layer has specific logging needs and levels.
    NO "UTIL" or other non-architectural types.
    """
    CONTROLLER = "controller"  # Job orchestration layer
    SERVICE = "service"        # Business logic layer
    REPOSITORY = "repository"  # Data access layer
    FACTORY = "factory"        # Object creation layer
    SCHEMA = "schema"          # Foundation layer
    TRIGGER = "trigger"        # Entry point layer
    ADAPTER = "adapter"        # External integration layer
    VALIDATOR = "validator"    # Validation layer (import validator, etc.)
    JOB = "job"                # Job class layer (15 DEC 2025)


# ============================================================================
# LOG LEVELS - Standard Python levels with enum safety
# ============================================================================

class LogLevel(Enum):
    """
    Standard Python log levels as enum for type safety.
    """
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    
    def to_python_level(self) -> int:
        """Convert to Python logging level constant."""
        return getattr(logging, self.value)
    
    @classmethod
    def from_string(cls, level: str) -> 'LogLevel':
        """Create from string, case-insensitive."""
        return cls[level.upper()]


# ============================================================================
# LOG CONTEXT - Correlation and tracking
# ============================================================================

@dataclass
class LogContext:
    """
    Context for log correlation across operations.
    
    Implements Robert's lineage pattern where task IDs
    contain stage information for multi-stage workflows.
    """
    # Job-level correlation
    job_id: Optional[str] = None  # Parent job ID
    job_type: Optional[str] = None  # Type of job
    
    # Task-level correlation
    task_id: Optional[str] = None  # Task ID with stage (a1b2c3d4-s2-tile_x5_y10)
    task_type: Optional[str] = None  # Type of task
    
    # Stage tracking
    stage: Optional[int] = None  # Current stage number
    
    # Request correlation
    correlation_id: Optional[str] = None  # Request correlation ID
    request_id: Optional[str] = None  # HTTP request ID
    
    # User context
    user_id: Optional[str] = None  # User identifier
    tenant_id: Optional[str] = None  # Tenant identifier
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            k: v for k, v in {
                'job_id': self.job_id,
                'job_type': self.job_type,
                'task_id': self.task_id,
                'task_type': self.task_type,
                'stage': self.stage,
                'correlation_id': self.correlation_id,
                'request_id': self.request_id,
                'user_id': self.user_id,
                'tenant_id': self.tenant_id
            }.items() if v is not None
        }


# ============================================================================
# COMPONENT CONFIGURATION - Per-component settings
# ============================================================================

@dataclass
class ComponentConfig:
    """
    Configuration for component-specific logging.
    
    Each component type can have different settings.
    """
    component_type: ComponentType
    log_level: LogLevel = LogLevel.INFO
    enable_performance_logging: bool = False
    enable_debug_context: bool = False
    max_message_length: int = 1000


# ============================================================================
# LOG EVENT - Structured log entry
# ============================================================================

def _utc_now() -> datetime:
    """Helper function to get current UTC time."""
    return datetime.now(timezone.utc)

@dataclass
class LogEvent:
    """
    Structured log event for consistent logging.
    
    This can be used for structured logging to external
    systems like Azure Application Insights.
    """
    # Core fields
    level: LogLevel
    message: str
    component_type: ComponentType
    component_name: str
    timestamp: datetime = field(default_factory=_utc_now)
    
    # Context
    context: Optional[LogContext] = None
    
    # Error information
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    
    # Performance metrics
    duration_ms: Optional[float] = None
    operation: Optional[str] = None
    
    # Custom dimensions for Azure
    custom_dimensions: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        result = {
            'timestamp': self.timestamp.isoformat(),
            'level': self.level.value,
            'message': self.message,
            'component_type': self.component_type.value,
            'component_name': self.component_name
        }
        
        # Add optional fields if present
        if self.context:
            result['context'] = self.context.to_dict()
        if self.error_type:
            result['error_type'] = self.error_type
        if self.error_message:
            result['error_message'] = self.error_message
        if self.stack_trace:
            result['stack_trace'] = self.stack_trace
        if self.duration_ms is not None:
            result['duration_ms'] = self.duration_ms
        if self.operation:
            result['operation'] = self.operation
        if self.custom_dimensions:
            result['custom_dimensions'] = self.custom_dimensions
            
        return result


# ============================================================================
# OPERATION RESULT - For tracking operation outcomes
# ============================================================================

@dataclass
class OperationResult:
    """
    Result of an operation for consistent success/failure logging.
    """
    success: bool
    operation: str
    component: ComponentType
    duration_ms: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def log_level(self) -> LogLevel:
        """Determine appropriate log level based on result."""
        if self.success:
            return LogLevel.INFO
        elif self.error_message and "critical" in self.error_message.lower():
            return LogLevel.CRITICAL
        else:
            return LogLevel.ERROR


# ============================================================================
# JSON FORMATTER - Structured logging for Azure Functions
# ============================================================================

class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging in Azure Functions.
    Outputs logs in a format that Application Insights can automatically parse.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON for Application Insights.
        
        Args:
            record: Python LogRecord to format
            
        Returns:
            JSON string with structured log data
        """
        # Build base log structure
        log_obj = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'logger': record.name,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add custom dimensions if present (for Application Insights)
        if hasattr(record, 'custom_dimensions'):
            log_obj['customDimensions'] = record.custom_dimensions
        
        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': self.formatException(record.exc_info) if record.exc_info else None
            }
        
        # Add any extra fields from the record
        if hasattr(record, 'extra_fields'):
            log_obj.update(record.extra_fields)
        
        return json.dumps(log_obj, default=str)


# ============================================================================
# LOGGER FACTORY - Creates component-specific loggers
# ============================================================================

class LoggerFactory:
    """
    Factory for creating component-specific loggers.

    This factory creates Python loggers configured for each
    component type with appropriate settings and context.

    Example:
        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "HelloWorldController"
        )
        logger.info("Processing job")
    """

    # Default configurations per component type
    # Check environment variable for debug mode (os imported at module level)
    _default_level = LogLevel.DEBUG if os.getenv('DEBUG_LOGGING', '').lower() == 'true' else LogLevel.INFO

    DEFAULT_CONFIGS = {
        ComponentType.CONTROLLER: ComponentConfig(
            component_type=ComponentType.CONTROLLER,
            log_level=_default_level,
            enable_performance_logging=True,
            enable_debug_context=True if _default_level == LogLevel.DEBUG else False
        ),
        ComponentType.SERVICE: ComponentConfig(
            component_type=ComponentType.SERVICE,
            log_level=_default_level,
            enable_performance_logging=True
        ),
        ComponentType.REPOSITORY: ComponentConfig(
            component_type=ComponentType.REPOSITORY,
            log_level=LogLevel.DEBUG,  # Always debug for repositories to track SQL
            enable_debug_context=True
        ),
        ComponentType.FACTORY: ComponentConfig(
            component_type=ComponentType.FACTORY,
            log_level=_default_level
        ),
        ComponentType.SCHEMA: ComponentConfig(
            component_type=ComponentType.SCHEMA,
            log_level=LogLevel.DEBUG  # Always debug for schema operations
        ),
        ComponentType.TRIGGER: ComponentConfig(
            component_type=ComponentType.TRIGGER,
            log_level=_default_level,
            enable_performance_logging=True
        ),
        ComponentType.ADAPTER: ComponentConfig(
            component_type=ComponentType.ADAPTER,
            log_level=_default_level,
            enable_performance_logging=True
        ),
        ComponentType.VALIDATOR: ComponentConfig(
            component_type=ComponentType.VALIDATOR,
            log_level=_default_level
        ),
        ComponentType.JOB: ComponentConfig(
            component_type=ComponentType.JOB,
            log_level=_default_level,
            enable_performance_logging=True  # Jobs benefit from timing info
        )
    }
    
    @classmethod
    def create_logger(
        cls,
        component_type: ComponentType,
        name: str,
        context: Optional[LogContext] = None,
        config: Optional[ComponentConfig] = None
    ) -> logging.Logger:
        """
        Create a logger for a specific component.
        
        Args:
            component_type: Type of component
            name: Component name (e.g., "HelloWorldController")
            context: Optional log context for correlation
            config: Optional custom configuration
            
        Returns:
            Configured Python logger
        """
        # Use custom config or default for component type
        if config is None:
            config = cls.DEFAULT_CONFIGS.get(
                component_type,
                ComponentConfig(component_type=component_type)
            )
        
        # Create hierarchical logger name
        logger_name = f"{component_type.value}.{name}"
        logger = logging.getLogger(logger_name)

        # Set log level - handle both LogLevel enum and string
        if isinstance(config.log_level, str):
            log_level = LogLevel.from_string(config.log_level).to_python_level()
        else:
            log_level = config.log_level.to_python_level()
        logger.setLevel(log_level)

        # Only add handlers if this logger doesn't already have our JSON handler
        # This prevents duplicate handlers when create_logger is called multiple times
        # (20 DEC 2025: Fixed handler duplication issue)
        has_json_handler = any(
            isinstance(h.formatter, JSONFormatter) for h in logger.handlers
        )
        if not has_json_handler:
            # Create console handler with JSON formatting
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(log_level)

            # Use JSON formatter for all output
            formatter = JSONFormatter()
            handler.setFormatter(formatter)

            # Add handler to logger
            logger.addHandler(handler)

        # Allow propagation to Azure's root logger for Application Insights
        logger.propagate = True

        # Create a wrapper that adds context as custom dimensions
        # Only wrap if not already wrapped (check for our marker attribute)
        if not hasattr(logger, '_context_wrapped'):
            original_log = logger._log

            def log_with_context(level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1):
                """Wrapper to inject context as custom dimensions."""
                if extra is None:
                    extra = {}

                # Build base custom dimensions from context
                if context:
                    custom_dims = context.to_dict()
                    custom_dims['component_type'] = component_type.value
                    custom_dims['component_name'] = name
                else:
                    custom_dims = {
                        'component_type': component_type.value,
                        'component_name': name
                    }

                # Merge with any custom_dimensions passed in extra (for DEBUG_MODE, etc.)
                if 'custom_dimensions' in extra:
                    custom_dims.update(extra['custom_dimensions'])

                extra['custom_dimensions'] = custom_dims

                # Call original log method with incremented stacklevel
                # +1 to account for this wrapper function (20 DEC 2025: Fixed stacklevel)
                original_log(level, msg, args, exc_info=exc_info, extra=extra,
                            stack_info=stack_info, stacklevel=stacklevel + 1)

            # Replace the _log method with our wrapper
            logger._log = log_with_context
            logger._context_wrapped = True  # Mark as wrapped to prevent re-wrapping

        return logger
    
    @classmethod
    def create_from_config(
        cls,
        config: ComponentConfig,
        name: str,
        context: Optional[LogContext] = None
    ) -> logging.Logger:
        """
        Create logger from explicit configuration.
        
        Args:
            config: Component configuration
            name: Component name
            context: Optional log context
            
        Returns:
            Configured Python logger
        """
        return cls.create_logger(
            component_type=config.component_type,
            name=name,
            context=context,
            config=config
        )
    
    @classmethod
    def create_with_context(
        cls,
        component_type: ComponentType,
        name: str,
        job_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: Optional[int] = None
    ) -> logging.Logger:
        """
        Create logger with job/task context.
        
        Convenience method for creating loggers with common context fields.
        
        Args:
            component_type: Type of component
            name: Component name
            job_id: Optional job ID
            task_id: Optional task ID
            stage: Optional stage number
            
        Returns:
            Configured Python logger with context
        """
        context = LogContext(
            job_id=job_id,
            task_id=task_id,
            stage=stage
        ) if any([job_id, task_id, stage]) else None
        
        return cls.create_logger(
            component_type=component_type,
            name=name,
            context=context
        )


# ============================================================================
# EXCEPTION DECORATOR - Automatic exception logging with context
# ============================================================================

def log_exceptions(component_type: Optional[ComponentType] = None, 
                  component_name: Optional[str] = None,
                  logger: Optional[logging.Logger] = None):
    """
    Decorator to automatically log exceptions with full context.
    
    Can be used in three ways:
    1. With existing logger: @log_exceptions(logger=my_logger)
    2. With component info: @log_exceptions(ComponentType.CONTROLLER, "MyController")
    3. Simple: @log_exceptions() - uses function module and name
    
    Args:
        component_type: Optional component type for creating logger
        component_name: Optional component name for creating logger
        logger: Optional existing logger to use
        
    Returns:
        Decorator function that wraps the target function
        
    Example:
        @log_exceptions(ComponentType.SERVICE, "DataService")
        def process_data(data):
            # If this throws, exception is logged automatically
            return transform(data)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Determine which logger to use
            if logger:
                log = logger
            elif component_type and component_name:
                log = LoggerFactory.create_logger(component_type, component_name)
            else:
                # Create a default logger based on function module
                log = LoggerFactory.create_logger(
                    ComponentType.SERVICE,  # Default to service
                    func.__module__ or "unknown"
                )
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Log with full exception context
                log.error(
                    f"Exception in {func.__name__}",
                    exc_info=True,
                    extra={
                        'custom_dimensions': {
                            'function_name': func.__name__,
                            'function_module': func.__module__,
                            'exception_type': type(e).__name__,
                            'exception_message': str(e),
                            'function_args': str(args)[:500],  # Limit size
                            'function_kwargs': str(kwargs)[:500],  # Limit size
                            'traceback': traceback.format_exc()
                        }
                    }
                )
                # Re-raise the exception - don't swallow it
                raise
        return wrapper
    return decorator


# ============================================================================
# NO LEGACY PATTERNS
# ============================================================================

# NO global logger instances
# NO setup_logger functions  
# NO get_logger with string-only parameters
# NO log_job_stage or other mixed-responsibility functions
# NO backward compatibility layers

# Everything is strongly typed and follows pyramid architecture