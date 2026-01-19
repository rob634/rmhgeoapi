# ============================================================================
# CLAUDE CONTEXT - CHECKPOINT MANAGER FOR DOCKER RESUME SUPPORT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Docker task checkpoint/resume management
# PURPOSE: Enable resumable Docker tasks with phase-based checkpointing
# LAST_REVIEWED: 16 JAN 2026
# EXPORTS: CheckpointManager, CheckpointValidationError
# DEPENDENCIES: core.schema.updates.TaskUpdateModel, threading
# F7.18: Added shutdown awareness (is_shutdown_requested, should_stop, etc.)
# ============================================================================
"""
Checkpoint Manager for Docker Resume Support.

Manages checkpoint state for resumable Docker tasks. When a Docker worker
picks up a task, it uses CheckpointManager to:
1. Check if the task was interrupted mid-execution
2. Resume from the last completed phase
3. Save progress after each phase completion

This follows the Kubernetes pattern where the orchestrator (Function App)
handles job-level concerns while the worker (Docker) handles task-internal
resilience.

Architecture (11 JAN 2026):
    ┌─────────────────────────────────────────────────────────────────┐
    │  FUNCTION APP ORCHESTRATOR (CoreMachine)                        │
    │  - Sees tasks as ATOMIC black boxes                             │
    │  - Handles: job submission, stage advancement, job completion   │
    │  - Doesn't know/care about Docker internal phases               │
    └─────────────────────────┬───────────────────────────────────────┘
                              │ Queue message
                              ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  DOCKER WORKER + CheckpointManager                              │
    │  - Picks up task message                                        │
    │  - Checks checkpoint_phase: "Did I crash mid-way?"              │
    │  - Resumes from last checkpoint OR starts fresh                 │
    │  - Updates checkpoint as it progresses                          │
    └─────────────────────────────────────────────────────────────────┘

Exports:
    CheckpointManager: Main class for checkpoint operations
    CheckpointValidationError: Raised when artifact validation fails
"""

import threading
from typing import Any, Callable, Dict, Optional
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType
from core.schema.updates import TaskUpdateModel

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "checkpoint_manager")


class CheckpointValidationError(Exception):
    """
    Raised when checkpoint artifact validation fails.

    This indicates that a phase claimed to complete but its output
    artifact is missing or invalid. The task should NOT save a checkpoint
    in this case - it needs to re-execute the phase.
    """
    pass


class CheckpointManager:
    """
    Manages checkpoint state for resumable Docker tasks.

    Each Docker task can have multiple internal phases (e.g., validation,
    COG creation, STAC metadata). CheckpointManager tracks which phases
    have completed and stores phase-specific data for resume scenarios.

    Usage:
        task_repo = RepositoryFactory.create_task_repository()
        checkpoint = CheckpointManager(task_id, task_repo)

        # Phase 1: Validation
        if not checkpoint.should_skip(1):
            result = do_validation()
            checkpoint.save(1, data={"validation": result})

        # Phase 2: COG Creation (uses data from phase 1)
        if not checkpoint.should_skip(2):
            validation = checkpoint.get_data("validation", {})
            cog_result = create_cog(validation)
            checkpoint.save(
                phase=2,
                data={"cog_blob": cog_result["blob_path"]},
                validate_artifact=lambda: blob_exists(cog_result["blob_path"])
            )

    Attributes:
        task_id: The task being checkpointed
        task_repo: Repository for task persistence
        current_phase: Last completed phase number (0 = not started)
        data: Accumulated checkpoint data from all phases
    """

    def __init__(self, task_id: str, task_repo, shutdown_event: Optional[threading.Event] = None):
        """
        Initialize CheckpointManager and load existing checkpoint.

        Args:
            task_id: Task ID to manage checkpoints for
            task_repo: Task repository with get_task and update_task methods
            shutdown_event: Optional threading.Event for graceful shutdown awareness.
                           When set, is_shutdown_requested() returns True.
        """
        self.task_id = task_id
        self.task_repo = task_repo
        self.current_phase: int = 0
        self.data: Dict[str, Any] = {}
        self._shutdown_event: Optional[threading.Event] = shutdown_event
        self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        """
        Load existing checkpoint from task record.

        Called automatically during __init__. If the task has a prior
        checkpoint, this restores the phase number and accumulated data.
        """
        task = self.task_repo.get_task(self.task_id)

        if task is None:
            logger.warning(f"⚠️ CheckpointManager: Task {self.task_id[:8]}... not found")
            return

        # Load checkpoint state from task record
        self.current_phase = task.checkpoint_phase or 0
        self.data = task.checkpoint_data or {}

        if self.current_phase > 0:
            logger.info("=" * 50)
            logger.info(f"🔄 CHECKPOINT RESUME DETECTED")
            logger.info(f"  Task ID: {self.task_id[:16]}...")
            logger.info(f"  Resuming from phase: {self.current_phase}")
            logger.info(f"  Checkpoint data keys: {list(self.data.keys())}")
            logger.info("=" * 50)
        else:
            logger.info(f"📍 CheckpointManager: Starting fresh for task {self.task_id[:16]}... (no prior checkpoint)")

    def should_skip(self, phase: int) -> bool:
        """
        Check if a phase was already completed.

        Use this before executing each phase to implement resume logic.
        If should_skip returns True, the phase output should already
        be available in checkpoint data.

        Args:
            phase: Phase number to check (1-indexed)

        Returns:
            True if phase was already completed, False if it needs to run

        Example:
            if not checkpoint.should_skip(1):
                logger.info("🔄 Phase 1: Validating...")
                result = validate()
                checkpoint.save(1, data={"validation": result})
            else:
                logger.info("⏭️ Phase 1: Skipping (already completed)")
        """
        return self.current_phase >= phase

    def save(
        self,
        phase: int,
        data: Optional[Dict[str, Any]] = None,
        validate_artifact: Optional[Callable[[], bool]] = None
    ) -> None:
        """
        Save checkpoint after completing a phase.

        This persists the phase number and any associated data to the
        task record in the database. If validate_artifact is provided,
        it's called first to ensure the phase output actually exists.

        Args:
            phase: Phase number just completed (1-indexed)
            data: Phase-specific data to merge into checkpoint.
                  This data will be available via get_data() after resume.
            validate_artifact: Optional callable that returns True if the
                             phase's output artifact exists and is valid.
                             Raises CheckpointValidationError if validation
                             fails.

        Raises:
            CheckpointValidationError: If validate_artifact returns False

        Example:
            # Simple checkpoint
            checkpoint.save(1, data={"row_count": 1000})

            # With artifact validation
            checkpoint.save(
                phase=2,
                data={"cog_blob": "container/path/file.tif"},
                validate_artifact=lambda: blob_repo.blob_exists(container, blob_path)
            )
        """
        # Validate artifact exists before saving checkpoint
        if validate_artifact is not None:
            if not validate_artifact():
                error_msg = f"Phase {phase} artifact validation failed for task {self.task_id[:8]}..."
                logger.error(f"❌ CheckpointManager: {error_msg}")
                raise CheckpointValidationError(error_msg)

        # Merge new data into accumulated checkpoint data
        merged_data = {**self.data, **(data or {})}

        # Persist to database
        update = TaskUpdateModel(
            checkpoint_phase=phase,
            checkpoint_data=merged_data,
            checkpoint_updated_at=datetime.now(timezone.utc)
        )

        success = self.task_repo.update_task(self.task_id, update)

        if success:
            # Update local state
            self.current_phase = phase
            self.data = merged_data
            logger.info(
                f"💾 CheckpointManager: Saved phase {phase} for task {self.task_id[:8]}... "
                f"(keys: {list(merged_data.keys())})"
            )
        else:
            logger.error(
                f"❌ CheckpointManager: Failed to save phase {phase} for task {self.task_id[:8]}..."
            )

    def get_data(self, key: str, default: Any = None) -> Any:
        """
        Get data from checkpoint.

        Use this to retrieve data saved in previous phases. This is
        essential for resume scenarios where later phases need output
        from earlier phases.

        Args:
            key: Data key to retrieve
            default: Value to return if key not found

        Returns:
            The stored value, or default if not found

        Example:
            # Phase 2 retrieves validation result from phase 1
            validation_result = checkpoint.get_data("validation", {})

            # Phase 3 retrieves COG path from phase 2
            cog_blob = checkpoint.get_data("cog_blob")
            if cog_blob:
                stac_result = create_stac_metadata(cog_blob)
        """
        return self.data.get(key, default)

    def get_all_data(self) -> Dict[str, Any]:
        """
        Get all accumulated checkpoint data.

        Returns:
            Complete checkpoint data dictionary
        """
        return self.data.copy()

    def reset(self) -> None:
        """
        Reset checkpoint to initial state.

        This clears the checkpoint phase and data, forcing all phases
        to re-execute. Use with caution - typically only for testing
        or explicit retry-from-scratch scenarios.
        """
        update = TaskUpdateModel(
            checkpoint_phase=0,
            checkpoint_data={},
            checkpoint_updated_at=datetime.now(timezone.utc)
        )

        success = self.task_repo.update_task(self.task_id, update)

        if success:
            self.current_phase = 0
            self.data = {}
            logger.warning(f"🔄 CheckpointManager: Reset checkpoint for task {self.task_id[:8]}...")
        else:
            logger.error(f"❌ CheckpointManager: Failed to reset task {self.task_id[:8]}...")

    # =========================================================================
    # SHUTDOWN AWARENESS (F7.18 - Docker Orchestration Framework)
    # =========================================================================

    def set_shutdown_event(self, shutdown_event: threading.Event) -> None:
        """
        Set the shutdown event for graceful shutdown awareness.

        This allows the shutdown event to be set after initialization,
        useful when the event is created by the worker infrastructure
        after the checkpoint manager is created.

        Args:
            shutdown_event: Threading event that signals shutdown request
        """
        self._shutdown_event = shutdown_event
        logger.debug(f"🔔 CheckpointManager: Shutdown event registered for task {self.task_id[:8]}...")

    def is_shutdown_requested(self) -> bool:
        """
        Check if a graceful shutdown has been requested.

        Returns True when the Docker worker receives SIGTERM and needs
        to stop processing. Handlers should check this periodically
        (e.g., between phases or iterations) and save checkpoint if True.

        Returns:
            True if shutdown was requested, False otherwise

        Example:
            for item in items:
                if checkpoint.is_shutdown_requested():
                    logger.info("Shutdown requested, saving checkpoint...")
                    checkpoint.save(phase, data={"processed": processed_count})
                    return  # Exit gracefully
                process(item)
        """
        if self._shutdown_event is None:
            return False
        is_set = self._shutdown_event.is_set()
        if is_set:
            logger.debug(f"🛑 CheckpointManager: Shutdown event IS SET for task {self.task_id[:8]}...")
        return is_set

    def should_stop(self) -> bool:
        """
        Alias for is_shutdown_requested() with a more intuitive name.

        Use in processing loops to check if work should stop:

            while items_to_process:
                if checkpoint.should_stop():
                    checkpoint.save(current_phase, data=progress)
                    return
                process_next_item()

        Returns:
            True if processing should stop (shutdown requested)
        """
        return self.is_shutdown_requested()

    def save_and_stop_if_requested(
        self,
        phase: int,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save checkpoint if shutdown requested, returning whether to stop.

        Convenience method that combines the common pattern of checking
        for shutdown, saving progress, and deciding whether to continue.

        Args:
            phase: Current phase number to checkpoint
            data: Data to save with checkpoint

        Returns:
            True if shutdown was requested (caller should return/stop),
            False if processing should continue

        Example:
            for i, item in enumerate(items):
                result = process(item)
                # Save progress and check for shutdown every 100 items
                if i % 100 == 0:
                    if checkpoint.save_and_stop_if_requested(
                        phase=1,
                        data={"processed": i, "last_result": result}
                    ):
                        return  # Graceful exit
        """
        if self.is_shutdown_requested():
            logger.warning("=" * 50)
            logger.warning(f"🛑 SHUTDOWN DETECTED - CheckpointManager")
            logger.warning(f"  Task ID: {self.task_id[:16]}...")
            logger.warning(f"  Current phase: {phase}")
            logger.warning(f"  Data keys: {list(data.keys()) if data else 'none'}")
            logger.warning(f"  Action: Saving checkpoint and signaling handler to stop")
            logger.warning("=" * 50)
            self.save(phase, data=data)
            logger.info(f"💾 Checkpoint saved at phase {phase} - handler should return interrupted=True")
            return True
        return False


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'CheckpointManager',
    'CheckpointValidationError',
]
