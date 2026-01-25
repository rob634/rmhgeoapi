# ============================================================================
# DOCKER TASK CONTEXT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - Docker task execution context
# PURPOSE: Unified context object for Docker handlers (F7.18)
# LAST_REVIEWED: 23 JAN 2026
# EXPORTS: DockerTaskContext
# DEPENDENCIES: infrastructure.checkpoint_manager, threading
# ============================================================================
"""
Docker Task Context for Handler Execution.

Provides a unified context object passed to Docker handlers, wrapping:
- CheckpointManager for resumable task execution
- Shutdown event for graceful termination
- Progress reporting for task visibility
- Task/Job identifiers
- Pulse mechanism for liveness tracking (22 JAN 2026)

================================================================================
ARCHITECTURE
================================================================================

    BackgroundQueueWorker (docker_service.py)
           │
           │ Creates DockerTaskContext with:
           │   - task_id, job_id
           │   - shutdown_event (shared across all tasks)
           │   - task_repo (for checkpoint persistence)
           │
           ▼
    CoreMachine.process_task_message(task_message, docker_context=context)
           │
           │ Injects _docker_context into handler params
           │
           ▼
    handler(params)
           │
           │ params['_docker_context'] = DockerTaskContext instance
           │
           ▼
    Handler uses context for:
           - context.should_stop() → check shutdown
           - context.checkpoint.should_skip(phase) → resume logic
           - context.checkpoint.save(phase, data) → save progress
           - context.report_progress(percent, message) → visibility

================================================================================
USAGE
================================================================================

Handler Pattern (NEW - uses DockerTaskContext):
```python
def my_handler(params: Dict) -> Dict:
    # Get context (available in Docker mode)
    context = params.get('_docker_context')

    if context:
        # Docker mode: use provided context
        checkpoint = context.checkpoint

        # Check for graceful shutdown
        if context.should_stop():
            return {'success': True, 'interrupted': True}
    else:
        # Function App mode: create checkpoint manually (backward compat)
        task_id = params.get('_task_id')
        if task_id:
            checkpoint = CheckpointManager(task_id, task_repo)
        else:
            checkpoint = None

    # Phase 1: Processing
    if not checkpoint or not checkpoint.should_skip(1):
        for i, item in enumerate(items):
            process(item)

            # Check shutdown periodically
            if context and context.should_stop():
                checkpoint.save(1, data={'processed': i})
                return {'success': True, 'interrupted': True}

        if checkpoint:
            checkpoint.save(1, data={'phase1_complete': True})

    return {'success': True, 'result': {...}}
```

================================================================================
EXPORTS
================================================================================

    DockerTaskContext: Main context dataclass for Docker handlers
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from util_logger import LoggerFactory, ComponentType

if TYPE_CHECKING:
    from infrastructure.checkpoint_manager import CheckpointManager

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "docker_context")

# =============================================================================
# PULSE CONFIGURATION (22 JAN 2026)
# =============================================================================
# Default interval for pulse updates (seconds)
# Can be overridden via DOCKER_PULSE_INTERVAL_SECONDS environment variable
DEFAULT_PULSE_INTERVAL_SECONDS = 60


# =============================================================================
# MEMORY WATCHDOG CONFIGURATION (24 JAN 2026)
# =============================================================================
# Monitor memory usage and trigger graceful shutdown before OOM kill.
# This allows handlers to save state before the kernel kills the process.
DEFAULT_MEMORY_THRESHOLD_PERCENT = 80  # Trigger shutdown at 80% of limit
MEMORY_CHECK_INTERVAL_SECONDS = 5      # Check memory every 5 seconds


@dataclass
class MemoryWatchdog:
    """
    Monitor memory usage and trigger graceful shutdown before OOM kill.

    When running in Docker, the container has a memory limit set via cgroups.
    If the process exceeds this limit, the kernel's OOM killer sends SIGKILL
    which cannot be caught - the process dies immediately with no chance to
    save state or log errors.

    This watchdog monitors memory usage and triggers graceful shutdown when
    approaching the limit, giving handlers time to checkpoint and exit cleanly.

    Architecture:
        MemoryWatchdog runs in background thread
              │
              ├── Reads memory limit from cgroups
              ├── Polls current memory usage every N seconds
              │
              └── When usage > threshold:
                    ├── Sets _oom_triggered = True
                    ├── Logs critical warning
                    └── Sets shutdown_event (shared with DockerTaskContext)
                              │
                              └── Handler's should_stop() returns True
                                        │
                                        └── Handler saves checkpoint and exits

    Usage:
        watchdog = MemoryWatchdog(
            threshold_percent=80,
            shutdown_event=context.shutdown_event
        )
        watchdog.start(task_id)
        # ... handler runs ...
        watchdog.stop()

    Attributes:
        threshold_percent: Memory usage % that triggers shutdown (default: 80)
        check_interval: Seconds between memory checks (default: 5)
        shutdown_event: Threading event to signal shutdown request
    """

    threshold_percent: float = DEFAULT_MEMORY_THRESHOLD_PERCENT
    check_interval: float = MEMORY_CHECK_INTERVAL_SECONDS
    shutdown_event: Optional[threading.Event] = None

    # Internal state (not passed to __init__)
    _thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _oom_triggered: bool = field(default=False, init=False, repr=False)
    _memory_limit_bytes: int = field(default=0, init=False, repr=False)
    _peak_memory_bytes: int = field(default=0, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)
    _task_id: str = field(default="", init=False, repr=False)

    def __post_init__(self):
        """Initialize memory limit from cgroups."""
        self._memory_limit_bytes = self._get_container_memory_limit()

    def _get_container_memory_limit(self) -> int:
        """
        Read container memory limit from cgroups.

        Docker sets memory limits via cgroups. We read from:
        - cgroups v2: /sys/fs/cgroup/memory.max
        - cgroups v1: /sys/fs/cgroup/memory/memory.limit_in_bytes

        Returns:
            Memory limit in bytes, or system total if not in container
        """
        # Try cgroups v2 first (modern systems)
        try:
            with open('/sys/fs/cgroup/memory.max', 'r') as f:
                limit = f.read().strip()
                if limit != 'max':
                    return int(limit)
        except (FileNotFoundError, ValueError, PermissionError):
            pass

        # Try cgroups v1 (older systems)
        try:
            with open('/sys/fs/cgroup/memory/memory.limit_in_bytes', 'r') as f:
                limit = int(f.read().strip())
                # Very high values indicate no limit
                if limit < 9223372036854771712:  # Near max int64
                    return limit
        except (FileNotFoundError, ValueError, PermissionError):
            pass

        # Fallback: use system memory (not in container or can't read cgroups)
        try:
            import psutil
            return psutil.virtual_memory().total
        except ImportError:
            # Last resort: assume 8GB
            return 8 * 1024 * 1024 * 1024

    def start(self, task_id: str) -> None:
        """
        Start background memory monitoring.

        Args:
            task_id: Task identifier for logging
        """
        if self._started:
            logger.debug(f"🧠 Memory watchdog already running for {task_id[:8]}...")
            return

        self._task_id = task_id
        self._stop_event.clear()
        self._oom_triggered = False

        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name=f"memwatch-{task_id[:8]}"
        )
        self._thread.start()
        self._started = True

        logger.info(
            f"🧠 Memory watchdog started for {task_id[:8]}... "
            f"(limit={self._memory_limit_bytes / 1e9:.1f}GB, "
            f"threshold={self.threshold_percent}%, "
            f"check_interval={self.check_interval}s)"
        )

    def stop(self) -> None:
        """Stop memory monitoring."""
        if not self._started:
            return

        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

        self._started = False

        logger.info(
            f"🧠 Memory watchdog stopped for {self._task_id[:8]}... "
            f"(peak={self._peak_memory_bytes / 1e9:.2f}GB, "
            f"oom_triggered={self._oom_triggered})"
        )

    def _get_container_memory_usage(self) -> int:
        """
        Read actual container memory usage from cgroups.

        This is CRITICAL for accurate memory monitoring because:
        - psutil.Process().rss only captures Python heap allocations
        - GDAL/rasterio use C memory allocations that don't appear in RSS
        - Memory-mapped files contribute to cgroup usage but not RSS

        Returns:
            Actual container memory usage in bytes from cgroups,
            or fallback to RSS if cgroups not available.
        """
        # Try cgroups v2 first (modern systems)
        try:
            with open('/sys/fs/cgroup/memory.current', 'r') as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError, PermissionError):
            pass

        # Try cgroups v1 (older systems)
        try:
            with open('/sys/fs/cgroup/memory/memory.usage_in_bytes', 'r') as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError, PermissionError):
            pass

        # Fallback to RSS (less accurate but better than nothing)
        try:
            import psutil
            return psutil.Process().memory_info().rss
        except ImportError:
            return 0

    def _monitor_loop(self) -> None:
        """Background loop checking memory usage."""
        try:
            import psutil
        except ImportError:
            logger.warning("🧠 psutil not available - limited fallback")

        task_id_short = self._task_id[:8] if self._task_id else "unknown"

        # Track whether we're using cgroups or RSS fallback
        using_cgroups = self._detect_cgroup_version()
        source = f"cgroups {using_cgroups}" if using_cgroups else "RSS fallback"
        logger.info(f"🧠 Memory monitoring source: {source}")

        while not self._stop_event.wait(timeout=self.check_interval):
            try:
                # Get actual container memory usage (NOT just Python RSS!)
                # This captures GDAL C allocations, memory-mapped files, etc.
                current_bytes = self._get_container_memory_usage()
                self._peak_memory_bytes = max(self._peak_memory_bytes, current_bytes)

                # Calculate usage percentage
                usage_percent = (current_bytes / self._memory_limit_bytes) * 100 if self._memory_limit_bytes > 0 else 0

                # Also get Python RSS for comparison (helps debug memory leaks vs C allocations)
                try:
                    python_rss = psutil.Process().memory_info().rss if 'psutil' in dir() else 0
                except Exception:
                    python_rss = 0

                # Log periodic status at INFO level for visibility during long-running tasks
                logger.info(
                    f"🧠 Memory: {usage_percent:.1f}% "
                    f"({current_bytes / 1e9:.2f}GB / {self._memory_limit_bytes / 1e9:.1f}GB) "
                    f"[Python RSS: {python_rss / 1e9:.2f}GB] "
                    f"[{task_id_short}...]"
                )

                # Check threshold
                if usage_percent >= self.threshold_percent:
                    self._oom_triggered = True

                    logger.critical(
                        f"🧠🚨 MEMORY WATCHDOG TRIGGERED for {task_id_short}...! "
                        f"Container usage: {usage_percent:.1f}% "
                        f"({current_bytes / 1e9:.2f}GB / {self._memory_limit_bytes / 1e9:.1f}GB) "
                        f"exceeds threshold {self.threshold_percent}% - "
                        f"Python RSS was only {python_rss / 1e9:.2f}GB (GDAL uses additional C memory) - "
                        f"REQUESTING GRACEFUL SHUTDOWN to prevent OOM kill"
                    )

                    # Trigger graceful shutdown via shared event
                    if self.shutdown_event:
                        self.shutdown_event.set()

                    # Exit monitoring loop
                    return

            except Exception as e:
                # Don't let monitoring errors kill the watchdog
                logger.warning(f"🧠 Memory check error: {e}")

        logger.debug(f"🧠 Memory watchdog loop ended for {task_id_short}...")

    def _detect_cgroup_version(self) -> Optional[str]:
        """Detect which cgroup version is available."""
        if os.path.exists('/sys/fs/cgroup/memory.current'):
            return 'v2'
        if os.path.exists('/sys/fs/cgroup/memory/memory.usage_in_bytes'):
            return 'v1'
        return None

    @property
    def oom_triggered(self) -> bool:
        """True if shutdown was triggered by memory pressure."""
        return self._oom_triggered

    @property
    def peak_memory_bytes(self) -> int:
        """Peak memory usage observed during monitoring."""
        return self._peak_memory_bytes

    @property
    def memory_limit_bytes(self) -> int:
        """Container memory limit in bytes."""
        return self._memory_limit_bytes

    @property
    def is_running(self) -> bool:
        """True if watchdog is currently monitoring."""
        return self._started and self._thread is not None and self._thread.is_alive()


@dataclass
class DockerTaskContext:
    """
    Unified context for Docker task handlers.

    Provides checkpoint management, shutdown awareness, progress reporting,
    and pulse mechanism in a single object passed to handlers via the
    _docker_context parameter.

    Attributes:
        task_id: Current task identifier
        job_id: Parent job identifier
        job_type: Job type name (e.g., 'process_raster_docker')
        stage: Current stage number
        checkpoint: CheckpointManager instance for resume support
        shutdown_event: Threading event signaling graceful shutdown
        task_repo: Task repository for progress updates (optional)
        pulse_interval_seconds: Interval between pulse updates (default: 60)
        created_at: When this context was created

    Pulse Mechanism (22 JAN 2026):
        The pulse mechanism updates task.last_pulse periodically to signal
        that the task is still alive. This allows the Janitor to distinguish
        between tasks that are legitimately running vs. tasks that crashed.

        Usage:
            context.start_pulse()  # Start background pulse thread
            # ... handler work ...
            context.stop_pulse()   # Stop pulse (automatic on context exit)

    Example:
        context = DockerTaskContext(
            task_id=task_id,
            job_id=job_id,
            job_type='h3_bootstrap_docker',
            stage=1,
            checkpoint=checkpoint_manager,
            shutdown_event=worker_stop_event,
        )

        # Start pulse before long-running work
        context.start_pulse()

        # In handler
        if context.should_stop():
            context.checkpoint.save(current_phase, data=progress)
            return {'success': True, 'interrupted': True}

        # Pulse stops automatically when context is cleaned up
    """

    # Core identifiers
    task_id: str
    job_id: str
    job_type: str
    stage: int

    # Checkpoint management (created by worker, shared with handler)
    checkpoint: CheckpointManager

    # Shutdown coordination (shared across all tasks in worker)
    shutdown_event: threading.Event

    # Optional: for progress reporting and pulse updates
    task_repo: Optional[Any] = None

    # Pulse configuration (22 JAN 2026)
    pulse_interval_seconds: int = field(default_factory=lambda: int(
        os.environ.get('DOCKER_PULSE_INTERVAL_SECONDS', DEFAULT_PULSE_INTERVAL_SECONDS)
    ))

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Pulse state (initialized in __post_init__)
    _pulse_thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _pulse_stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _pulse_count: int = field(default=0, init=False, repr=False)
    _pulse_started: bool = field(default=False, init=False, repr=False)

    # Memory watchdog state (24 JAN 2026)
    _memory_watchdog: Optional[MemoryWatchdog] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        """Wire shutdown event to checkpoint manager."""
        if self.checkpoint and self.shutdown_event:
            self.checkpoint.set_shutdown_event(self.shutdown_event)

    # =========================================================================
    # PULSE MECHANISM (22 JAN 2026)
    # =========================================================================

    def start_pulse(self) -> None:
        """
        Start the background pulse thread.

        The pulse thread updates task.last_pulse periodically to signal
        that the task is still running. This allows the Janitor to distinguish
        between active tasks and crashed tasks.

        Call this at the start of long-running handler work.
        Pulse stops automatically on shutdown or when stop_pulse() is called.
        """
        if self._pulse_started:
            logger.debug(f"💓 Pulse already running for task {self.task_id[:8]}...")
            return

        if not self.task_repo:
            logger.warning(
                f"💔 Cannot start pulse for task {self.task_id[:8]}... - no task_repo"
            )
            return

        self._pulse_stop_event.clear()
        self._pulse_thread = threading.Thread(
            target=self._pulse_loop,
            daemon=True,
            name=f"pulse-{self.task_id[:8]}"
        )
        self._pulse_thread.start()
        self._pulse_started = True

        logger.info(
            f"💓 Started pulse thread for task {self.task_id[:8]}... "
            f"(interval={self.pulse_interval_seconds}s)"
        )

    def stop_pulse(self) -> None:
        """
        Stop the background pulse thread.

        Called automatically when shutdown is signaled, or can be called
        explicitly at the end of handler work.
        """
        if not self._pulse_started:
            return

        self._pulse_stop_event.set()

        if self._pulse_thread and self._pulse_thread.is_alive():
            self._pulse_thread.join(timeout=5)

        self._pulse_started = False

        logger.info(
            f"💓 Stopped pulse thread for task {self.task_id[:8]}... "
            f"(total pulses: {self._pulse_count})"
        )

    def _pulse_loop(self) -> None:
        """
        Background thread loop that updates last_pulse periodically.

        Runs until stop_pulse() is called or shutdown is signaled.
        """
        logger.debug(f"💓 Pulse loop started for task {self.task_id[:8]}...")

        while not self._pulse_stop_event.wait(timeout=self.pulse_interval_seconds):
            # Check for shutdown
            if self.shutdown_event.is_set():
                logger.debug(f"💓 Pulse loop stopping (shutdown) for task {self.task_id[:8]}...")
                break

            try:
                # Update last_pulse in database
                success = self.task_repo.update_task_pulse(self.task_id)
                self._pulse_count += 1

                if success:
                    logger.debug(
                        f"💓 Pulse #{self._pulse_count} for task {self.task_id[:8]}..."
                    )
                else:
                    logger.warning(
                        f"💔 Pulse #{self._pulse_count} failed for task {self.task_id[:8]}..."
                    )

            except Exception as e:
                # Pulse failure is non-fatal - log and continue
                logger.warning(
                    f"💔 Pulse error for task {self.task_id[:8]}...: {e}"
                )

        logger.debug(f"💓 Pulse loop ended for task {self.task_id[:8]}...")

    @property
    def pulse_count(self) -> int:
        """Number of successful pulse updates."""
        return self._pulse_count

    @property
    def is_pulse_running(self) -> bool:
        """Check if pulse thread is currently running."""
        return self._pulse_started and self._pulse_thread is not None and self._pulse_thread.is_alive()

    # =========================================================================
    # MEMORY WATCHDOG MECHANISM (24 JAN 2026)
    # =========================================================================

    def start_memory_watchdog(
        self,
        threshold_percent: float = DEFAULT_MEMORY_THRESHOLD_PERCENT,
        check_interval: float = MEMORY_CHECK_INTERVAL_SECONDS
    ) -> None:
        """
        Start memory monitoring to prevent OOM kills.

        The memory watchdog monitors container memory usage and triggers
        graceful shutdown before hitting the limit. When memory usage
        exceeds the threshold, shutdown_event is set, causing should_stop()
        to return True. The handler then has time to save checkpoint and
        exit cleanly instead of being killed by SIGKILL.

        Args:
            threshold_percent: Memory usage % that triggers shutdown (default: 80)
            check_interval: Seconds between memory checks (default: 5)

        Example:
            context.start_memory_watchdog(threshold_percent=75)
            for item in items:
                if context.should_stop():
                    if context.oom_abort_requested:
                        logger.warning("Stopping due to memory pressure")
                    context.checkpoint.save(phase, data)
                    return {'success': True, 'interrupted': True}
                process(item)
        """
        if self._memory_watchdog is not None and self._memory_watchdog.is_running:
            logger.debug(f"🧠 Memory watchdog already running for {self.task_id[:8]}...")
            return

        self._memory_watchdog = MemoryWatchdog(
            threshold_percent=threshold_percent,
            check_interval=check_interval,
            shutdown_event=self.shutdown_event
        )
        self._memory_watchdog.start(self.task_id)

    def stop_memory_watchdog(self) -> None:
        """
        Stop memory monitoring.

        Called automatically when task completes. Returns memory statistics
        via logging for observability.
        """
        if self._memory_watchdog is not None:
            self._memory_watchdog.stop()

    @property
    def oom_abort_requested(self) -> bool:
        """
        True if shutdown was triggered by memory pressure (vs SIGTERM).

        Use this to distinguish between:
        - OOM prevention: Handler exceeded memory threshold
        - Normal shutdown: SIGTERM from container stop/scale-down

        Example:
            if context.should_stop():
                if context.oom_abort_requested:
                    logger.warning("Memory pressure - saving checkpoint")
                else:
                    logger.info("Graceful shutdown requested")
                context.checkpoint.save(...)
        """
        if self._memory_watchdog is not None:
            return self._memory_watchdog.oom_triggered
        return False

    @property
    def memory_watchdog_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get memory watchdog statistics.

        Returns:
            Dict with limit_gb, peak_gb, oom_triggered, is_running
            or None if watchdog not started
        """
        if self._memory_watchdog is None:
            return None

        return {
            'limit_gb': self._memory_watchdog.memory_limit_bytes / 1e9,
            'peak_gb': self._memory_watchdog.peak_memory_bytes / 1e9,
            'threshold_percent': self._memory_watchdog.threshold_percent,
            'oom_triggered': self._memory_watchdog.oom_triggered,
            'is_running': self._memory_watchdog.is_running,
        }

    def log_memory_status(self, checkpoint_name: str = "") -> Dict[str, Any]:
        """
        Log current memory status (on-demand, for handler use).

        Use this at key checkpoints in handlers to track memory progression
        through different phases of processing.

        Args:
            checkpoint_name: Label for this checkpoint (e.g., "before_cog_translate")

        Returns:
            Dict with current memory metrics

        Example:
            context.log_memory_status("before_download")
            data = download_large_file()
            context.log_memory_status("after_download")
        """
        if self._memory_watchdog is None:
            logger.warning(f"🧠 Memory status ({checkpoint_name}): watchdog not started")
            return {}

        current = self._memory_watchdog._get_container_memory_usage()
        limit = self._memory_watchdog.memory_limit_bytes
        peak = self._memory_watchdog.peak_memory_bytes
        usage_pct = (current / limit * 100) if limit > 0 else 0
        threshold = self._memory_watchdog.threshold_percent
        headroom = threshold - usage_pct

        # Get Python RSS for comparison
        try:
            import psutil
            python_rss = psutil.Process().memory_info().rss
        except Exception:
            python_rss = 0

        metrics = {
            'checkpoint': checkpoint_name,
            'current_gb': current / 1e9,
            'peak_gb': peak / 1e9,
            'limit_gb': limit / 1e9,
            'usage_percent': usage_pct,
            'python_rss_gb': python_rss / 1e9,
            'threshold_percent': threshold,
            'headroom_percent': headroom,
        }

        status_emoji = "🟢" if headroom > 20 else "🟡" if headroom > 10 else "🔴"

        logger.info(
            f"🧠 {status_emoji} Memory [{checkpoint_name}]: "
            f"{usage_pct:.1f}% ({current / 1e9:.2f}GB / {limit / 1e9:.1f}GB) "
            f"[Python: {python_rss / 1e9:.2f}GB] "
            f"[Peak: {peak / 1e9:.2f}GB] "
            f"[Headroom: {headroom:.1f}%]"
        )

        return metrics

    # =========================================================================
    # SHUTDOWN AWARENESS
    # =========================================================================

    def should_stop(self) -> bool:
        """
        Check if the handler should stop processing.

        Returns True when a graceful shutdown has been requested
        (e.g., SIGTERM received by Docker worker). Handlers should
        check this periodically and save checkpoint before returning.

        Returns:
            True if shutdown requested, False to continue processing

        Example:
            for item in items:
                if context.should_stop():
                    context.checkpoint.save(phase, data={'last_item': item.id})
                    return {'success': True, 'interrupted': True, 'resumable': True}
                process(item)
        """
        return self.shutdown_event.is_set()

    def is_shutdown_requested(self) -> bool:
        """Alias for should_stop() - matches CheckpointManager API."""
        return self.should_stop()

    # =========================================================================
    # PROGRESS REPORTING
    # =========================================================================

    def report_progress(
        self,
        percent: float,
        message: Optional[str] = None,
        items_processed: Optional[int] = None,
        items_total: Optional[int] = None
    ) -> None:
        """
        Report task progress for monitoring visibility.

        Updates the task record with progress information that can be
        queried via the jobs API. Useful for long-running tasks to
        show progress in dashboards.

        Args:
            percent: Progress percentage (0.0 to 100.0)
            message: Optional status message
            items_processed: Optional count of items processed
            items_total: Optional total item count

        Example:
            for i, item in enumerate(items):
                process(item)
                if i % 100 == 0:  # Update every 100 items
                    context.report_progress(
                        percent=(i / len(items)) * 100,
                        message=f"Processing item {i}",
                        items_processed=i,
                        items_total=len(items)
                    )
        """
        if not self.task_repo:
            logger.debug(
                f"Progress report skipped (no task_repo): "
                f"{percent:.1f}% - {message or 'no message'}"
            )
            return

        try:
            # Build progress metadata
            progress_data = {
                'percent': round(percent, 1),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }
            if message:
                progress_data['message'] = message
            if items_processed is not None:
                progress_data['items_processed'] = items_processed
            if items_total is not None:
                progress_data['items_total'] = items_total

            # Use update_task_metadata with merge=True to preserve other metadata
            # This is the proper way to update progress without losing checkpoint data
            self.task_repo.update_task_metadata(
                self.task_id,
                {'progress': progress_data},
                merge=True
            )

            logger.debug(
                f"📊 Progress: {self.task_id[:8]}... - {percent:.1f}% "
                f"({message or 'no message'})"
            )

        except Exception as e:
            # Progress reporting is non-critical - log and continue
            logger.warning(f"Failed to report progress: {e}")

    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================

    def save_and_stop_if_requested(
        self,
        phase: int,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save checkpoint if shutdown requested, returning whether to stop.

        Convenience method that delegates to checkpoint manager.

        Args:
            phase: Current phase number to checkpoint
            data: Data to save with checkpoint

        Returns:
            True if shutdown was requested (handler should return),
            False if processing should continue

        Example:
            for i, item in enumerate(items):
                result = process(item)
                if i % 100 == 0:
                    if context.save_and_stop_if_requested(1, {'processed': i}):
                        return {'success': True, 'interrupted': True}
        """
        return self.checkpoint.save_and_stop_if_requested(phase, data)

    def get_checkpoint_phase(self) -> int:
        """Get the current checkpoint phase (0 if not started)."""
        return self.checkpoint.current_phase

    def get_checkpoint_data(self, key: str, default: Any = None) -> Any:
        """Get data from checkpoint."""
        return self.checkpoint.get_data(key, default)


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_docker_context(
    task_id: str,
    job_id: str,
    job_type: str,
    stage: int,
    shutdown_event: threading.Event,
    task_repo: Any,
    auto_start_pulse: bool = True,
    pulse_interval_seconds: Optional[int] = None,
    enable_memory_watchdog: bool = False,
    memory_threshold_percent: float = DEFAULT_MEMORY_THRESHOLD_PERCENT,
    memory_check_interval: float = MEMORY_CHECK_INTERVAL_SECONDS,
) -> DockerTaskContext:
    """
    Factory function to create DockerTaskContext with CheckpointManager.

    This is the preferred way to create context in BackgroundQueueWorker,
    as it handles CheckpointManager creation and wiring.

    Args:
        task_id: Task identifier
        job_id: Parent job identifier
        job_type: Job type name
        stage: Current stage number
        shutdown_event: Worker's shutdown event
        task_repo: Task repository for persistence
        auto_start_pulse: Whether to start pulse thread immediately (default: True)
        pulse_interval_seconds: Override pulse interval (default: from env or 60s)
        enable_memory_watchdog: Start memory monitoring (default: False)
        memory_threshold_percent: Memory % that triggers shutdown (default: 80)
        memory_check_interval: Seconds between memory checks (default: 5)

    Returns:
        Fully configured DockerTaskContext with pulse and watchdog optionally started

    Example:
        # In BackgroundQueueWorker._process_message()
        context = create_docker_context(
            task_id=task_message.task_id,
            job_id=task_message.parent_job_id,
            job_type=task_message.job_type,
            stage=task_message.stage,
            shutdown_event=self._stop_event,
            task_repo=task_repo,
            enable_memory_watchdog=True,  # Prevent OOM kills
            memory_threshold_percent=75,   # More conservative threshold
        )
        # Pulse and memory watchdog are running!
        result = self._core_machine.process_task_message(
            task_message,
            docker_context=context
        )
        # Stop pulse and watchdog when done
        context.stop_pulse()
        context.stop_memory_watchdog()
    """
    from infrastructure.checkpoint_manager import CheckpointManager

    # Create checkpoint manager with shutdown awareness
    checkpoint = CheckpointManager(
        task_id=task_id,
        task_repo=task_repo,
        shutdown_event=shutdown_event
    )

    # Build context kwargs
    context_kwargs = {
        'task_id': task_id,
        'job_id': job_id,
        'job_type': job_type,
        'stage': stage,
        'checkpoint': checkpoint,
        'shutdown_event': shutdown_event,
        'task_repo': task_repo,
    }

    # Add pulse interval if specified
    if pulse_interval_seconds is not None:
        context_kwargs['pulse_interval_seconds'] = pulse_interval_seconds

    context = DockerTaskContext(**context_kwargs)

    # Auto-start pulse if requested
    if auto_start_pulse:
        context.start_pulse()

    # Start memory watchdog if requested (24 JAN 2026)
    if enable_memory_watchdog:
        context.start_memory_watchdog(
            threshold_percent=memory_threshold_percent,
            check_interval=memory_check_interval
        )

    return context


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'DockerTaskContext',
    'MemoryWatchdog',
    'create_docker_context',
    'DEFAULT_MEMORY_THRESHOLD_PERCENT',
    'MEMORY_CHECK_INTERVAL_SECONDS',
]
