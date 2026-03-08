# ============================================================================
# DAG TASK EXECUTOR
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Handler execution with timing and error handling
# PURPOSE: Execute handler functions safely with metrics
# CREATED: 29 JAN 2026
# ============================================================================
"""
DAG Task Executor

Executes handler functions with:
- Timeout enforcement
- Error handling and capture
- Execution timing
- Graceful shutdown support

The executor is the bridge between queue messages and handler functions.
"""

import asyncio
import logging
import signal
import time
from typing import Any, Dict, Optional, Tuple

from .contracts import TaskMessage, TaskResult, TaskStatus
from .handler_registry import get_handler, has_handler

logger = logging.getLogger(__name__)


class TaskExecutor:
    """
    Executes DAG tasks safely.

    Features:
    - Looks up handler by name
    - Enforces timeout
    - Captures errors
    - Tracks execution duration
    - Supports graceful shutdown
    """

    def __init__(self, worker_id: str):
        """
        Initialize executor.

        Args:
            worker_id: Identifier for this worker instance
        """
        self.worker_id = worker_id
        self.shutdown_requested = False
        self._current_task: Optional[TaskMessage] = None

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)

    def _handle_sigterm(self, signum, frame):
        """Handle shutdown signal."""
        logger.info(f"Received signal {signum}, requesting shutdown")
        self.shutdown_requested = True

    async def execute(self, task: TaskMessage) -> TaskResult:
        """
        Execute a task.

        Args:
            task: TaskMessage from the queue

        Returns:
            TaskResult with success or failure
        """
        self._current_task = task
        start_time = time.time()

        logger.info(
            f"Executing task {task.task_id}: "
            f"handler={task.handler}, job={task.job_id}, node={task.node_id}"
        )

        try:
            # Check if handler exists
            if not has_handler(task.handler):
                raise KeyError(f"Unknown handler: {task.handler}")

            # Get handler function
            handler = get_handler(task.handler)

            # Execute with timeout
            result = await asyncio.wait_for(
                self._run_handler(handler, task.params),
                timeout=task.timeout_seconds,
            )

            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"Task {task.task_id} completed successfully "
                f"in {duration_ms}ms"
            )

            return TaskResult.success(
                task=task,
                output=result if isinstance(result, dict) else {"result": result},
                duration_ms=duration_ms,
                worker_id=self.worker_id,
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Task timed out after {task.timeout_seconds} seconds"

            logger.error(f"Task {task.task_id} timed out: {error_msg}")

            return TaskResult.failure(
                task=task,
                error_message=error_msg,
                duration_ms=duration_ms,
                worker_id=self.worker_id,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"{type(e).__name__}: {str(e)}"

            logger.exception(f"Task {task.task_id} failed: {error_msg}")

            return TaskResult.failure(
                task=task,
                error_message=error_msg,
                duration_ms=duration_ms,
                worker_id=self.worker_id,
            )

        finally:
            self._current_task = None

    async def _run_handler(
        self,
        handler,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Run a handler function.

        Handles both sync and async handlers.

        Args:
            handler: Handler function
            params: Parameters to pass

        Returns:
            Handler result
        """
        # Check if async
        if asyncio.iscoroutinefunction(handler):
            return await handler(params)
        else:
            # Run sync handler in thread pool
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, handler, params)

    @property
    def is_busy(self) -> bool:
        """Check if executor is currently running a task."""
        return self._current_task is not None

    @property
    def current_task_id(self) -> Optional[str]:
        """Get ID of currently executing task."""
        return self._current_task.task_id if self._current_task else None


class ExecutorPool:
    """
    Pool of executors for concurrent task execution.

    Manages multiple executors for parallel task processing.
    """

    def __init__(self, worker_id: str, max_concurrent: int = 1):
        """
        Initialize executor pool.

        Args:
            worker_id: Worker identifier
            max_concurrent: Maximum concurrent tasks
        """
        self.worker_id = worker_id
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._executor = TaskExecutor(worker_id)
        self._active_count = 0

    async def execute(self, task: TaskMessage) -> TaskResult:
        """
        Execute a task, respecting concurrency limits.

        Args:
            task: Task to execute

        Returns:
            TaskResult
        """
        async with self._semaphore:
            self._active_count += 1
            try:
                return await self._executor.execute(task)
            finally:
                self._active_count -= 1

    @property
    def active_count(self) -> int:
        """Number of currently executing tasks."""
        return self._active_count

    @property
    def available_slots(self) -> int:
        """Number of available execution slots."""
        return self.max_concurrent - self._active_count

    @property
    def shutdown_requested(self) -> bool:
        """Check if shutdown was requested."""
        return self._executor.shutdown_requested
