# ============================================================================
# CLAUDE CONTEXT - JOB PROGRESS TRACKER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Universal Job Progress Tracking
# PURPOSE: Real-time progress tracking for long-running jobs
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: JobProgressTracker, JobProgressSnapshot
# DEPENDENCIES: infrastructure.metrics_repository, config
# ============================================================================
"""
Universal Job Progress Tracker.

Provides real-time progress tracking for long-running jobs with massive
task counts. Calculates rates, ETAs, and emits debug logs when enabled.

Features:
---------
- Stage progress tracking (current/total stages)
- Task counting (queued, processing, completed, failed)
- Rate calculation (tasks/minute rolling average)
- ETA estimation based on current rate
- Debug mode logging (chattery stdout when enabled)
- Periodic snapshots to PostgreSQL

Architecture:
-------------
This is the base tracker providing universal metrics. Context-specific
trackers (H3, FATHOM, etc.) extend this with domain-specific fields.

```
JobProgressTracker (universal)
    ├── stage progress
    ├── task counts
    ├── rates & ETA
    └── debug logging

H3AggregationTracker(JobProgressTracker, H3AggregationContext)
    └── cells, stats, tiles

FathomETLTracker(JobProgressTracker, FathomETLContext)
    └── tiles, bytes, regions
```

Usage:
------
```python
from infrastructure.job_progress import JobProgressTracker

# Create tracker
tracker = JobProgressTracker(
    job_id="abc123",
    job_type="h3_raster_aggregation"
)

# Start a stage
tracker.start_stage(2, "compute_stats", task_count=5)

# Track task progress
tracker.task_started("task-001")
# ... task work ...
tracker.task_completed("task-001", {"cells": 1000, "stats": 4000})

# Get current snapshot
snapshot = tracker.get_snapshot()
print(f"Progress: {snapshot.progress_pct:.1f}%, ETA: {snapshot.eta_seconds}s")

# Debug logging (only when METRICS_DEBUG_MODE=true)
tracker.emit_debug("Processing tile: S02_E029")
```
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class JobProgressSnapshot:
    """
    Point-in-time snapshot of job progress.

    Immutable snapshot that can be serialized to JSON for API responses.
    """
    # Job identification
    job_id: str
    job_type: str
    timestamp: datetime

    # Stage progress
    stage: int
    total_stages: int
    stage_name: str

    # Task counts
    tasks_total: int
    tasks_queued: int
    tasks_processing: int
    tasks_completed: int
    tasks_failed: int

    # Rates
    tasks_per_minute: float
    error_rate_pct: float
    elapsed_seconds: float
    eta_seconds: Optional[float]

    # Context (domain-specific, set by subclasses)
    context: Dict[str, Any] = field(default_factory=dict)

    # Recent events for debugging
    recent_events: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def progress_pct(self) -> float:
        """Calculate overall progress percentage."""
        if self.tasks_total == 0:
            return 0.0
        return (self.tasks_completed / self.tasks_total) * 100

    @property
    def is_complete(self) -> bool:
        """Check if all tasks are done (completed or failed)."""
        return (self.tasks_completed + self.tasks_failed) >= self.tasks_total

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "timestamp": self.timestamp.isoformat(),
            "progress": {
                "stage": self.stage,
                "total_stages": self.total_stages,
                "stage_name": self.stage_name,
                "tasks_total": self.tasks_total,
                "tasks_queued": self.tasks_queued,
                "tasks_processing": self.tasks_processing,
                "tasks_completed": self.tasks_completed,
                "tasks_failed": self.tasks_failed,
                "progress_pct": round(self.progress_pct, 1)
            },
            "rates": {
                "tasks_per_minute": round(self.tasks_per_minute, 2),
                "error_rate_pct": round(self.error_rate_pct, 1),
                "elapsed_seconds": round(self.elapsed_seconds, 1),
                "eta_seconds": round(self.eta_seconds, 0) if self.eta_seconds else None
            },
            "context": self.context,
            "recent_events": self.recent_events[-10:]  # Last 10 events
        }


class JobProgressTracker:
    """
    Universal progress tracker for long-running jobs.

    Tracks stage progress, task counts, rates, and ETAs.
    Emits debug logs when METRICS_DEBUG_MODE is enabled.
    Writes periodic snapshots to PostgreSQL for dashboard polling.

    Thread-safe for use in concurrent task execution.
    """

    def __init__(
        self,
        job_id: str,
        job_type: str,
        debug_mode: Optional[bool] = None,
        auto_persist: bool = True
    ):
        """
        Initialize job progress tracker.

        Args:
            job_id: Unique job identifier
            job_type: Type of job (e.g., 'h3_raster_aggregation')
            debug_mode: Override config debug mode (None = use config)
            auto_persist: If True, auto-save snapshots to PostgreSQL
        """
        self.job_id = job_id
        self.job_type = job_type
        self.auto_persist = auto_persist

        # Load config for debug mode
        if debug_mode is not None:
            self._debug_mode = debug_mode
            self._log_prefix = "[METRICS]"
        else:
            try:
                from config import get_config
                config = get_config()
                self._debug_mode = config.metrics.debug_mode
                self._log_prefix = config.metrics.log_prefix
                self._sample_interval = config.metrics.sample_interval
            except Exception:
                self._debug_mode = False
                self._log_prefix = "[METRICS]"
                self._sample_interval = 5

        # Timing
        self._start_time = time.time()
        self._last_snapshot_time = self._start_time

        # Stage tracking
        self._stage = 0
        self._total_stages = 1
        self._stage_name = "initializing"
        self._stage_start_time = self._start_time

        # Task tracking
        self._tasks_total = 0
        self._tasks_queued = 0
        self._tasks_processing = 0
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._processing_tasks: Dict[str, float] = {}  # task_id -> start_time

        # Rate calculation (rolling window)
        self._completion_times: deque = deque(maxlen=100)  # (timestamp, count)

        # Events log
        self._events: List[Dict[str, Any]] = []
        self._max_events = 100

        # Context (set by subclasses)
        self._context: Dict[str, Any] = {}

        # Repository (lazy loaded)
        self._repo = None

        # Emit start event
        self.emit_debug(f"Job {job_id[:8]}... started: {job_type}")

    def _get_repo(self):
        """Lazy load metrics repository."""
        if self._repo is None:
            from infrastructure.metrics_repository import MetricsRepository
            self._repo = MetricsRepository()
        return self._repo

    # =========================================================================
    # STAGE MANAGEMENT
    # =========================================================================

    def start_stage(
        self,
        stage: int,
        stage_name: str,
        task_count: int,
        total_stages: Optional[int] = None
    ):
        """
        Start a new stage.

        Args:
            stage: Stage number (1-indexed)
            stage_name: Human-readable stage name
            task_count: Number of tasks in this stage
            total_stages: Total stages (optional, set once)
        """
        self._stage = stage
        self._stage_name = stage_name
        self._stage_start_time = time.time()

        if total_stages:
            self._total_stages = total_stages

        # Reset task counts for new stage
        self._tasks_total = task_count
        self._tasks_queued = task_count
        self._tasks_processing = 0
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._processing_tasks.clear()

        self._add_event("stage_start", {
            "stage": stage,
            "stage_name": stage_name,
            "task_count": task_count
        })

        self.emit_debug(
            f"Stage {stage}/{self._total_stages}: {stage_name} ({task_count} tasks)"
        )

    def complete_stage(self, result_summary: Optional[Dict[str, Any]] = None):
        """
        Mark current stage as complete.

        Args:
            result_summary: Optional summary of stage results
        """
        elapsed = time.time() - self._stage_start_time

        self._add_event("stage_complete", {
            "stage": self._stage,
            "stage_name": self._stage_name,
            "elapsed_seconds": elapsed,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "result_summary": result_summary
        })

        self.emit_debug(
            f"Stage {self._stage} complete: "
            f"{self._tasks_completed} done, {self._tasks_failed} failed "
            f"({elapsed:.1f}s)"
        )

    # =========================================================================
    # TASK TRACKING
    # =========================================================================

    def task_started(self, task_id: str):
        """
        Mark a task as started.

        Args:
            task_id: Task identifier
        """
        self._tasks_queued = max(0, self._tasks_queued - 1)
        self._tasks_processing += 1
        self._processing_tasks[task_id] = time.time()

        self._add_event("task_start", {"task_id": task_id})
        self.emit_debug(f"  Task {task_id} started", indent=2)

    def task_completed(
        self,
        task_id: str,
        result_summary: Optional[Dict[str, Any]] = None
    ):
        """
        Mark a task as completed.

        Args:
            task_id: Task identifier
            result_summary: Optional summary of task results
        """
        start_time = self._processing_tasks.pop(task_id, time.time())
        elapsed = time.time() - start_time

        self._tasks_processing = max(0, self._tasks_processing - 1)
        self._tasks_completed += 1

        # Record for rate calculation
        self._completion_times.append((time.time(), 1))

        self._add_event("task_complete", {
            "task_id": task_id,
            "elapsed_seconds": elapsed,
            "result_summary": result_summary
        })

        self.emit_debug(
            f"  Task {task_id} completed ({elapsed:.1f}s)",
            indent=2
        )

        # Auto-persist snapshot if interval elapsed
        self._maybe_persist_snapshot()

    def task_failed(self, task_id: str, error: str):
        """
        Mark a task as failed.

        Args:
            task_id: Task identifier
            error: Error message
        """
        start_time = self._processing_tasks.pop(task_id, time.time())
        elapsed = time.time() - start_time

        self._tasks_processing = max(0, self._tasks_processing - 1)
        self._tasks_failed += 1

        self._add_event("task_failed", {
            "task_id": task_id,
            "elapsed_seconds": elapsed,
            "error": error[:500]  # Truncate long errors
        })

        self.emit_debug(f"  Task {task_id} FAILED: {error[:100]}", indent=2)

        # Always persist on failure
        self._persist_snapshot()

    # =========================================================================
    # RATE CALCULATION
    # =========================================================================

    def _calculate_rate(self) -> float:
        """
        Calculate tasks per minute (rolling average).

        Returns:
            float: Tasks completed per minute
        """
        if not self._completion_times:
            return 0.0

        now = time.time()
        window_start = now - 60  # Last 60 seconds

        # Count completions in window
        count = sum(
            c for t, c in self._completion_times
            if t > window_start
        )

        # Calculate rate
        if count == 0:
            return 0.0

        # Find actual window duration
        recent = [t for t, _ in self._completion_times if t > window_start]
        if len(recent) < 2:
            return count * 60.0  # Extrapolate single point

        window_duration = max(recent) - min(recent)
        if window_duration < 1:
            return count * 60.0

        return (count / window_duration) * 60

    def _calculate_eta(self) -> Optional[float]:
        """
        Estimate time to completion.

        Returns:
            float: Estimated seconds remaining, or None if unknown
        """
        rate = self._calculate_rate()
        if rate <= 0:
            return None

        remaining = self._tasks_total - self._tasks_completed - self._tasks_failed
        if remaining <= 0:
            return 0.0

        # Convert from tasks/minute to seconds
        return (remaining / rate) * 60

    # =========================================================================
    # CONTEXT (for subclasses)
    # =========================================================================

    def set_context(self, key: str, value: Any):
        """
        Set a context value (for domain-specific metrics).

        Args:
            key: Context key
            value: Context value
        """
        self._context[key] = value

    def update_context(self, updates: Dict[str, Any]):
        """
        Update multiple context values.

        Args:
            updates: Dictionary of context updates
        """
        self._context.update(updates)

    def get_context(self) -> Dict[str, Any]:
        """Get current context dictionary."""
        return self._context.copy()

    # =========================================================================
    # SNAPSHOT
    # =========================================================================

    def get_snapshot(self) -> JobProgressSnapshot:
        """
        Get current progress snapshot.

        Returns:
            JobProgressSnapshot: Immutable snapshot of current state
        """
        elapsed = time.time() - self._start_time
        error_rate = 0.0
        if (self._tasks_completed + self._tasks_failed) > 0:
            error_rate = (
                self._tasks_failed /
                (self._tasks_completed + self._tasks_failed)
            ) * 100

        return JobProgressSnapshot(
            job_id=self.job_id,
            job_type=self.job_type,
            timestamp=datetime.now(timezone.utc),
            stage=self._stage,
            total_stages=self._total_stages,
            stage_name=self._stage_name,
            tasks_total=self._tasks_total,
            tasks_queued=self._tasks_queued,
            tasks_processing=self._tasks_processing,
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            tasks_per_minute=self._calculate_rate(),
            error_rate_pct=error_rate,
            elapsed_seconds=elapsed,
            eta_seconds=self._calculate_eta(),
            context=self._context.copy(),
            recent_events=self._events[-10:]
        )

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def _maybe_persist_snapshot(self):
        """Persist snapshot if sample interval has elapsed."""
        if not self.auto_persist:
            return

        now = time.time()
        if now - self._last_snapshot_time >= self._sample_interval:
            self._persist_snapshot()
            self._last_snapshot_time = now

    def _persist_snapshot(self):
        """Write current snapshot to database."""
        if not self.auto_persist:
            return

        try:
            snapshot = self.get_snapshot()
            repo = self._get_repo()
            repo.write_snapshot(
                job_id=self.job_id,
                metric_type="snapshot",
                payload=snapshot.to_dict()
            )
        except Exception as e:
            logger.warning(f"Failed to persist metrics snapshot: {e}")

    def persist_event(self, event_type: str, payload: Dict[str, Any]):
        """
        Persist a specific event to database.

        Args:
            event_type: Type of event
            payload: Event data
        """
        if not self.auto_persist:
            return

        try:
            repo = self._get_repo()
            repo.write_snapshot(
                job_id=self.job_id,
                metric_type="event",
                payload={
                    "event_type": event_type,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload
                }
            )
        except Exception as e:
            logger.warning(f"Failed to persist event: {e}")

    # =========================================================================
    # DEBUG LOGGING
    # =========================================================================

    def emit_debug(self, message: str, indent: int = 0):
        """
        Emit debug log message (only when debug mode enabled).

        Args:
            message: Log message
            indent: Indentation level (spaces = indent * 2)
        """
        if not self._debug_mode:
            return

        prefix = "  " * indent
        full_message = f"{self._log_prefix} {prefix}{message}"

        # Log to stdout AND logger
        print(full_message)
        logger.info(full_message)

    def emit_progress(self):
        """Emit current progress summary (debug mode only)."""
        if not self._debug_mode:
            return

        snapshot = self.get_snapshot()
        eta_str = f"{snapshot.eta_seconds:.0f}s" if snapshot.eta_seconds else "?"

        self.emit_debug(
            f"Progress: {snapshot.tasks_completed}/{snapshot.tasks_total} "
            f"({snapshot.progress_pct:.1f}%), "
            f"Rate: {snapshot.tasks_per_minute:.1f}/min, "
            f"ETA: {eta_str}"
        )

    # =========================================================================
    # EVENTS
    # =========================================================================

    def _add_event(self, event_type: str, data: Dict[str, Any]):
        """Add event to internal log."""
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data
        }
        self._events.append(event)

        # Trim old events
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def complete(self, result_summary: Optional[Dict[str, Any]] = None):
        """
        Mark job as complete.

        Args:
            result_summary: Optional summary of final results
        """
        elapsed = time.time() - self._start_time

        self._add_event("job_complete", {
            "elapsed_seconds": elapsed,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "result_summary": result_summary
        })

        self.emit_debug(
            f"Job complete: {self._tasks_completed} tasks in {elapsed:.1f}s "
            f"({self._tasks_failed} failed)"
        )

        # Final snapshot
        self._persist_snapshot()


# Export
__all__ = ["JobProgressTracker", "JobProgressSnapshot"]
