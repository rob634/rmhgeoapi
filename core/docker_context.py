# ============================================================================
# DOCKER TASK CONTEXT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - Docker task execution context
# PURPOSE: Unified context object for Docker handlers (F7.18)
# LAST_REVIEWED: 16 JAN 2026
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

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from util_logger import LoggerFactory, ComponentType

if TYPE_CHECKING:
    from infrastructure.checkpoint_manager import CheckpointManager

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "docker_context")


@dataclass
class DockerTaskContext:
    """
    Unified context for Docker task handlers.

    Provides checkpoint management, shutdown awareness, and progress reporting
    in a single object passed to handlers via the _docker_context parameter.

    Attributes:
        task_id: Current task identifier
        job_id: Parent job identifier
        job_type: Job type name (e.g., 'process_raster_docker')
        stage: Current stage number
        checkpoint: CheckpointManager instance for resume support
        shutdown_event: Threading event signaling graceful shutdown
        task_repo: Task repository for progress updates (optional)
        created_at: When this context was created

    Example:
        context = DockerTaskContext(
            task_id=task_id,
            job_id=job_id,
            job_type='h3_bootstrap_docker',
            stage=1,
            checkpoint=checkpoint_manager,
            shutdown_event=worker_stop_event,
        )

        # In handler
        if context.should_stop():
            context.checkpoint.save(current_phase, data=progress)
            return {'success': True, 'interrupted': True}
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

    # Optional: for progress reporting
    task_repo: Optional[Any] = None

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Wire shutdown event to checkpoint manager."""
        if self.checkpoint and self.shutdown_event:
            self.checkpoint.set_shutdown_event(self.shutdown_event)

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

    Returns:
        Fully configured DockerTaskContext

    Example:
        # In BackgroundQueueWorker._process_message()
        context = create_docker_context(
            task_id=task_message.task_id,
            job_id=task_message.parent_job_id,
            job_type=task_message.job_type,
            stage=task_message.stage,
            shutdown_event=self._stop_event,
            task_repo=task_repo,
        )
        result = self._core_machine.process_task_message(
            task_message,
            docker_context=context
        )
    """
    from infrastructure.checkpoint_manager import CheckpointManager

    # Create checkpoint manager with shutdown awareness
    checkpoint = CheckpointManager(
        task_id=task_id,
        task_repo=task_repo,
        shutdown_event=shutdown_event
    )

    return DockerTaskContext(
        task_id=task_id,
        job_id=job_id,
        job_type=job_type,
        stage=stage,
        checkpoint=checkpoint,
        shutdown_event=shutdown_event,
        task_repo=task_repo,
    )


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'DockerTaskContext',
    'create_docker_context',
]
