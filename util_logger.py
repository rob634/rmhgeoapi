# ============================================================================
# UNIFIED LOGGER SYSTEM
# ============================================================================
# STATUS: Core - Structured logging and resource monitoring
# PURPOSE: JSON logging for Azure Application Insights + memory/CPU/DB monitoring
# LAST_REVIEWED: 10 JAN 2026
# REVIEW_STATUS: Updated for F7.12 observability consolidation
# ============================================================================
"""
Unified Logger System.

JSON-only structured logging for Azure Functions with Application Insights.

Design Principles:
    - Strong typing with dataclasses (stdlib only)
    - Enum safety for categories
    - Component-specific loggers
    - Clean factory pattern
    - Global log context for multi-app filtering (10 JAN 2026)

Observability Mode (10 JAN 2026 - F7.12.C):
    Uses unified OBSERVABILITY_MODE flag instead of separate DEBUG_MODE/DEBUG_LOGGING.
    Features controlled by OBSERVABILITY_MODE:
    - Memory/CPU tracking (get_memory_stats, log_memory_checkpoint)
    - Database stats collection (get_database_stats)
    - Verbose diagnostics

    For log verbosity, use LOG_LEVEL=DEBUG instead of DEBUG_LOGGING=true.

Global Log Context (10 JAN 2026 - F7.12.A):
    Every log entry automatically includes:
    - app_name: Application identifier (APP_NAME env var)
    - app_instance: Azure instance ID (WEBSITE_INSTANCE_ID)
    - environment: Deployment environment (ENVIRONMENT env var)

    This enables filtering logs by component in multi-app deployments.

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
    get_database_environment: Database server config (PostgreSQL version, settings) - cached
    get_database_stats: Database utilization snapshot (connections, cache, locks)
    log_database_checkpoint: Database checkpoint logger (utilization, cache ratios)
    get_global_log_context: Get global log context fields

Dependencies:
    Standard library only (logging, enum, dataclasses, json)
    Optional: psutil (lazy import for memory tracking in observability mode)
    Optional: config (lazy import for observability mode check)
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
# GLOBAL LOG CONTEXT (10 JAN 2026 - F7.12.A)
# ============================================================================
# Cached global context fields injected into every log entry.
# Enables filtering logs by app/instance in multi-app deployments.

_GLOBAL_LOG_CONTEXT: Optional[Dict[str, str]] = None


def get_global_log_context() -> Dict[str, str]:
    """
    Get global log context fields for multi-app filtering.

    Returns cached context containing:
    - app_name: Application identifier (APP_NAME env var)
    - app_instance: Azure instance ID (truncated to 16 chars)
    - environment: Deployment environment (dev/qa/prod)

    These fields are automatically injected into every log entry
    by LoggerFactory, enabling queries like:
        traces | where customDimensions.app_name == "rmhogcstac"

    Returns:
        Dict with app_name, app_instance, environment
    """
    global _GLOBAL_LOG_CONTEXT

    if _GLOBAL_LOG_CONTEXT is None:
        _GLOBAL_LOG_CONTEXT = {
            "app_name": os.environ.get("APP_NAME", "unknown"),
            "app_instance": os.environ.get("WEBSITE_INSTANCE_ID", "local")[:16],
            "environment": os.environ.get("ENVIRONMENT", "dev"),
        }

    return _GLOBAL_LOG_CONTEXT


def _is_observability_enabled() -> bool:
    """
    Check if observability mode is enabled (10 JAN 2026).

    Uses config.observability.enabled which checks env vars in priority order:
    1. OBSERVABILITY_MODE (new preferred)
    2. METRICS_DEBUG_MODE (legacy)
    3. DEBUG_MODE (legacy)

    Returns:
        bool: True if observability features should be active
    """
    try:
        from config import get_config
        return get_config().is_observability_enabled()
    except Exception:
        # Fallback: check env vars directly if config import fails
        for var in ("OBSERVABILITY_MODE", "METRICS_DEBUG_MODE", "DEBUG_MODE"):
            val = os.environ.get(var, "").lower()
            if val in ("true", "1", "yes"):
                return True
        return False


# ============================================================================
# OBSERVABILITY MODE - Lazy imports for memory tracking (Updated 10 JAN 2026)
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

    Only executes if OBSERVABILITY_MODE is enabled.

    Returns:
        dict with resource stats or None if observability disabled or psutil unavailable
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

    # Check if observability mode enabled (10 JAN 2026: unified flag)
    if not _is_observability_enabled():
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
    Only executes if OBSERVABILITY_MODE is enabled.

    Returns:
        dict with environment info or None if observability disabled:
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

    # Check if observability mode enabled (10 JAN 2026: unified flag)
    if not _is_observability_enabled():
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

    Only logs if OBSERVABILITY_MODE is enabled. Otherwise, this is a no-op.
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
            # Get existing metadata to append to memory_snapshots list
            existing_metadata = task_repo.get_task_metadata(task_id) or {}
            existing_snapshots = existing_metadata.get("memory_snapshots", [])

            # Append new snapshot to list (not replace)
            updated_snapshots = existing_snapshots + [snapshot]

            task_repo.update_task_metadata(
                task_id,
                {
                    "memory_snapshots": updated_snapshots,
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


# ============================================================================
# DATABASE UTILIZATION STATS - PostgreSQL performance monitoring (23 DEC 2025)
# ============================================================================
# Mirrors memory tracking pattern but for database:
# - get_database_environment(): Static server config (cached)
# - get_database_stats(): Current utilization snapshot
# - log_database_checkpoint(): Log checkpoint with DB stats

# Cached database environment (computed once, refreshed on demand)
_database_environment: Optional[Dict[str, Any]] = None
_database_environment_updated: Optional[float] = None
_DATABASE_ENV_CACHE_TTL_SECONDS = 300  # Refresh every 5 minutes

# Default connection timeout for database stats queries
_DATABASE_STATS_TIMEOUT_SECONDS = 60


def _get_database_connection(timeout_seconds: int = _DATABASE_STATS_TIMEOUT_SECONDS):
    """
    Get a fresh database connection for stats queries.

    Creates its own connection with specified timeout to avoid
    blocking other operations if database is under pressure.

    Args:
        timeout_seconds: Connection and query timeout

    Returns:
        psycopg connection or None if connection fails
    """
    try:
        import psycopg
        from config import get_config

        config = get_config()

        # Build connection string based on auth method
        if config.database.use_managed_identity:
            # Get token for managed identity auth
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")

            conn_str = (
                f"host={config.database.host} "
                f"port={config.database.port} "
                f"dbname={config.database.database} "
                f"user={config.database.managed_identity_admin_name} "
                f"password={token.token} "
                f"sslmode=require "
                f"connect_timeout={timeout_seconds}"
            )
        else:
            # Password auth
            conn_str = (
                f"host={config.database.host} "
                f"port={config.database.port} "
                f"dbname={config.database.database} "
                f"user={config.database.user} "
                f"password={config.database.password} "
                f"sslmode=require "
                f"connect_timeout={timeout_seconds}"
            )

        # Create connection with statement timeout
        conn = psycopg.connect(
            conn_str,
            autocommit=True,
            options=f"-c statement_timeout={timeout_seconds * 1000}"  # Convert to ms
        )

        return conn

    except Exception as e:
        _logger = logging.getLogger("util_logger.database_stats")
        _logger.warning(f"⚠️ Database stats connection failed: {e}")
        return None


def get_database_environment(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get database environment info (PostgreSQL version, config, etc.).

    Cached after first call with TTL-based refresh. Use force_refresh=True
    to bypass cache.

    Returns:
        dict with database environment info or None if unavailable:
        {
            'postgresql_version': str,      # e.g., "17.2"
            'postgis_version': str,         # e.g., "3.5 USE_GEOS=1..."
            'database_name': str,           # Database name
            'database_size_mb': float,      # Database size in MB
            'max_connections': int,         # max_connections setting
            'shared_buffers': str,          # e.g., "128MB"
            'work_mem': str,                # e.g., "4MB"
            'effective_cache_size': str,    # e.g., "4GB"
            'last_updated': str,            # ISO timestamp of last refresh
        }
    """
    global _database_environment, _database_environment_updated

    current_time = time.time()

    # Return cached result if valid and not forcing refresh
    if (not force_refresh
        and _database_environment is not None
        and _database_environment_updated is not None
        and current_time - _database_environment_updated < _DATABASE_ENV_CACHE_TTL_SECONDS):
        return _database_environment

    conn = None
    try:
        conn = _get_database_connection(timeout_seconds=30)  # Shorter timeout for env
        if not conn:
            return _database_environment  # Return stale cache if available

        with conn.cursor() as cur:
            # PostgreSQL version
            cur.execute("SELECT version()")
            pg_version_full = cur.fetchone()[0]
            # Extract just version number (e.g., "PostgreSQL 17.2" -> "17.2")
            pg_version = pg_version_full.split()[1] if pg_version_full else "unknown"

            # PostGIS version
            postgis_version = "not installed"
            try:
                cur.execute("SELECT PostGIS_Version()")
                postgis_version = cur.fetchone()[0]
            except Exception:
                pass

            # Database name and size
            cur.execute("SELECT current_database()")
            db_name = cur.fetchone()[0]

            cur.execute("SELECT pg_database_size(current_database())")
            db_size_bytes = cur.fetchone()[0]
            db_size_mb = round(db_size_bytes / (1024 * 1024), 1) if db_size_bytes else 0

            # Key configuration settings
            cur.execute("SHOW max_connections")
            max_conn = int(cur.fetchone()[0])

            cur.execute("SHOW shared_buffers")
            shared_buffers = cur.fetchone()[0]

            cur.execute("SHOW work_mem")
            work_mem = cur.fetchone()[0]

            cur.execute("SHOW effective_cache_size")
            effective_cache = cur.fetchone()[0]

            _database_environment = {
                'postgresql_version': pg_version,
                'postgis_version': postgis_version,
                'database_name': db_name,
                'database_size_mb': db_size_mb,
                'max_connections': max_conn,
                'shared_buffers': shared_buffers,
                'work_mem': work_mem,
                'effective_cache_size': effective_cache,
                'last_updated': datetime.now(timezone.utc).isoformat(),
            }
            _database_environment_updated = current_time

            return _database_environment

    except Exception as e:
        _logger = logging.getLogger("util_logger.database_stats")
        _logger.warning(f"⚠️ Database environment query failed: {e}")
        return _database_environment  # Return stale cache if available

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_database_stats() -> Optional[Dict[str, Any]]:
    """
    Get current database utilization snapshot.

    Queries PostgreSQL for real-time performance metrics.
    Only executes if OBSERVABILITY_MODE is enabled.

    Returns:
        dict with database stats or None if observability disabled or query fails:
        {
            'connection_utilization_percent': float,  # (total / max_connections) * 100
            'active_connections': int,                # Currently executing queries
            'idle_connections': int,                  # Connected but waiting
            'total_connections': int,                 # Total connections
            'max_connections': int,                   # Server max_connections
            'cache_hit_ratio': float,                 # Buffer cache effectiveness (0.0-1.0)
            'index_hit_ratio': float,                 # Index usage effectiveness (0.0-1.0)
            'long_running_queries': int,              # Queries running > 5 min
            'locks_waiting': int,                     # Queries blocked on locks
            'oldest_transaction_sec': float,          # Age of oldest open transaction
            'xact_commit_rate': float,                # Commits since stats reset
            'xact_rollback_rate': float,              # Rollback ratio
        }
    """
    _logger = logging.getLogger("util_logger.database_stats")

    # Check if observability mode enabled (10 JAN 2026: unified flag)
    if not _is_observability_enabled():
        return None

    conn = None
    try:
        conn = _get_database_connection()
        if not conn:
            return None

        with conn.cursor() as cur:
            # Connection pool stats
            cur.execute("""
                SELECT
                    count(*) as total,
                    count(*) FILTER (WHERE state = 'active') as active,
                    count(*) FILTER (WHERE state = 'idle') as idle,
                    count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction,
                    count(*) FILTER (WHERE wait_event_type = 'Lock') as locks_waiting
                FROM pg_stat_activity
                WHERE backend_type = 'client backend'
            """)
            row = cur.fetchone()
            total_conn = row[0] or 0
            active_conn = row[1] or 0
            idle_conn = row[2] or 0
            idle_in_tx = row[3] or 0
            locks_waiting = row[4] or 0

            # Max connections
            cur.execute("SHOW max_connections")
            max_conn = int(cur.fetchone()[0])

            utilization = round((total_conn / max_conn * 100), 1) if max_conn > 0 else 0

            # Cache hit ratio (buffer cache effectiveness)
            cur.execute("""
                SELECT
                    sum(heap_blks_hit) / NULLIF(sum(heap_blks_hit + heap_blks_read), 0)
                FROM pg_statio_user_tables
            """)
            cache_hit = cur.fetchone()[0]
            cache_hit_ratio = round(float(cache_hit), 4) if cache_hit else 0.0

            # Index hit ratio
            cur.execute("""
                SELECT
                    sum(idx_blks_hit) / NULLIF(sum(idx_blks_hit + idx_blks_read), 0)
                FROM pg_statio_user_indexes
            """)
            index_hit = cur.fetchone()[0]
            index_hit_ratio = round(float(index_hit), 4) if index_hit else 0.0

            # Long-running queries (> 5 minutes)
            cur.execute("""
                SELECT count(*)
                FROM pg_stat_activity
                WHERE state = 'active'
                AND now() - query_start > interval '5 minutes'
                AND pid != pg_backend_pid()
            """)
            long_queries = cur.fetchone()[0] or 0

            # Oldest transaction age
            cur.execute("""
                SELECT EXTRACT(EPOCH FROM (now() - min(xact_start)))
                FROM pg_stat_activity
                WHERE xact_start IS NOT NULL
                AND pid != pg_backend_pid()
            """)
            oldest_tx = cur.fetchone()[0]
            oldest_tx_sec = round(float(oldest_tx), 1) if oldest_tx else 0.0

            # Transaction stats (commits/rollbacks)
            cur.execute("""
                SELECT xact_commit, xact_rollback
                FROM pg_stat_database
                WHERE datname = current_database()
            """)
            tx_row = cur.fetchone()
            xact_commit = tx_row[0] or 0
            xact_rollback = tx_row[1] or 0
            total_tx = xact_commit + xact_rollback
            rollback_ratio = round(xact_rollback / total_tx, 4) if total_tx > 0 else 0.0

            return {
                'connection_utilization_percent': utilization,
                'active_connections': active_conn,
                'idle_connections': idle_conn,
                'idle_in_transaction': idle_in_tx,
                'total_connections': total_conn,
                'max_connections': max_conn,
                'cache_hit_ratio': cache_hit_ratio,
                'index_hit_ratio': index_hit_ratio,
                'long_running_queries': long_queries,
                'locks_waiting': locks_waiting,
                'oldest_transaction_sec': oldest_tx_sec,
                'xact_commit_total': xact_commit,
                'xact_rollback_total': xact_rollback,
                'rollback_ratio': rollback_ratio,
            }

    except Exception as e:
        _logger.warning(f"⚠️ Database stats query failed: {e}")
        return None

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def log_database_checkpoint(
    logger: logging.Logger,
    checkpoint_name: str,
    context_id: Optional[str] = None,
    **extra_fields
):
    """
    Log a database utilization checkpoint with stats.

    Only logs if OBSERVABILITY_MODE is enabled. Otherwise, this is a no-op.
    Mirrors log_memory_checkpoint() but for database metrics.

    Args:
        logger: Python logger instance
        checkpoint_name: Descriptive name for this checkpoint
        context_id: Optional task/job ID for tracking
        **extra_fields: Additional context fields (e.g., query_type="bulk_insert")

    Example:
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "bulk_loader")
        log_database_checkpoint(logger, "Before bulk insert", context_id=task_id)
        # ... execute bulk insert ...
        log_database_checkpoint(logger, "After bulk insert", context_id=task_id, rows=50000)
    """
    db_stats = get_database_stats()
    if db_stats:
        # Merge all fields
        all_fields = {
            **db_stats,
            **extra_fields,
            'checkpoint': checkpoint_name,
            'checkpoint_type': 'database',
        }

        # Add context_id if provided
        if context_id:
            all_fields['context_id'] = context_id[:16] if len(context_id) > 16 else context_id

        logger.info(f"📊 DATABASE CHECKPOINT: {checkpoint_name}", extra={'custom_dimensions': all_fields})


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
# JSONL BLOB HANDLER - Singleton for blob log exports (11 JAN 2026 - F7.12.F)
# ============================================================================

_jsonl_handler: Optional[logging.Handler] = None
_jsonl_handler_lock = threading.Lock()


def _get_jsonl_handler() -> Optional[logging.Handler]:
    """
    Get singleton JSONL blob handler for log exports.

    Lazy initialization to avoid import issues at module load.
    Only creates handler if observability mode is enabled.

    Returns:
        JSONLBlobHandler instance or None if disabled
    """
    global _jsonl_handler

    if _jsonl_handler is not None:
        return _jsonl_handler

    with _jsonl_handler_lock:
        if _jsonl_handler is not None:
            return _jsonl_handler

        # Check if observability is enabled before creating handler
        if not _is_observability_enabled():
            return None

        try:
            from infrastructure.jsonl_log_handler import JSONLBlobHandler
            _jsonl_handler = JSONLBlobHandler()
            return _jsonl_handler
        except ImportError:
            # Module not available - skip JSONL logging
            return None
        except Exception:
            # Don't let handler initialization break app startup
            return None


# ============================================================================
# LOGGER FACTORY - Creates component-specific loggers
# ============================================================================

class LoggerFactory:
    """
    Factory for creating component-specific loggers.

    This factory creates Python loggers configured for each
    component type with appropriate settings and context.

    Global Context (10 JAN 2026):
        Every log entry automatically includes app_name, app_instance,
        and environment from get_global_log_context().

    JSONL Blob Export (11 JAN 2026 - F7.12.F):
        When OBSERVABILITY_MODE=true, logs are also exported to Azure
        Blob Storage as JSONL files. The JSONLBlobHandler is automatically
        attached to all loggers created by this factory.

    Example:
        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "HelloWorldController"
        )
        logger.info("Processing job")
        # Log will include: app_name, app_instance, environment
        # Log will also be exported to blob storage if observability enabled
    """

    # Default configurations per component type
    # Use LOG_LEVEL env var instead of DEBUG_LOGGING (10 JAN 2026)
    _default_level = LogLevel.DEBUG if os.getenv('LOG_LEVEL', 'INFO').upper() == 'DEBUG' else LogLevel.INFO

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

            # Add JSONL blob handler if observability enabled (11 JAN 2026 - F7.12.F)
            jsonl_handler = _get_jsonl_handler()
            if jsonl_handler is not None:
                # Check if handler not already attached (avoid duplicates)
                if jsonl_handler not in logger.handlers:
                    logger.addHandler(jsonl_handler)

        # Allow propagation to Azure's root logger for Application Insights
        logger.propagate = True

        # Create a wrapper that adds context as custom dimensions
        # Only wrap if not already wrapped (check for our marker attribute)
        if not hasattr(logger, '_context_wrapped'):
            original_log = logger._log

            def log_with_context(level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1):
                """Wrapper to inject context and global context as custom dimensions."""
                if extra is None:
                    extra = {}

                # Start with global log context (10 JAN 2026 - F7.12.A)
                # This enables multi-app filtering in Application Insights
                custom_dims = get_global_log_context().copy()

                # Add component info
                custom_dims['component_type'] = component_type.value
                custom_dims['component_name'] = name

                # Add request context if provided
                if context:
                    custom_dims.update(context.to_dict())

                # Merge with any custom_dimensions passed in extra
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