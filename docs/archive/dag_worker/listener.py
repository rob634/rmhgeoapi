# ============================================================================
# DAG QUEUE LISTENER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Service Bus queue consumer
# PURPOSE: Listen for DAG tasks and dispatch to executor
# CREATED: 29 JAN 2026
# ============================================================================
"""
DAG Queue Listener

Polls the dag-worker-tasks queue for task messages.
For each message:
1. Deserialize to TaskMessage
2. Execute via TaskExecutor
3. Report result via ResultReporter
4. Complete/abandon message

Runs as an async background task alongside the Epoch 4 listener.
"""

import asyncio
import json
import logging
from typing import Optional

from azure.servicebus.aio import ServiceBusClient, ServiceBusReceiver
from azure.servicebus import ServiceBusReceivedMessage

from .config import DagWorkerConfig
from .contracts import TaskMessage, TaskResult
from .executor import ExecutorPool
from .reporter import ResultReporter

logger = logging.getLogger(__name__)


class DagListener:
    """
    Listens for DAG tasks from Service Bus queue.

    This is the main entry point for the DAG worker.
    It runs continuously, processing tasks as they arrive.
    """

    def __init__(self, config: DagWorkerConfig):
        """
        Initialize listener.

        Args:
            config: DAG worker configuration
        """
        self.config = config
        self._client: Optional[ServiceBusClient] = None
        self._receiver: Optional[ServiceBusReceiver] = None
        self._executor: Optional[ExecutorPool] = None
        self._reporter: Optional[ResultReporter] = None
        self._running = False
        self._tasks_processed = 0
        self._tasks_failed = 0

    async def start(self) -> None:
        """Initialize connections and resources."""
        if not self.config.enabled:
            logger.info("DAG listener is disabled (DAG_QUEUE_ENABLED=false)")
            return

        errors = self.config.validate()
        if errors:
            raise ValueError(f"Invalid configuration: {errors}")

        logger.info(f"Starting DAG listener on queue: {self.config.queue_name}")

        # Create Service Bus client
        self._client = ServiceBusClient.from_connection_string(
            self.config.queue_connection
        )

        # Create receiver
        self._receiver = self._client.get_queue_receiver(
            queue_name=self.config.queue_name,
            max_wait_time=5,  # Seconds to wait for messages
        )

        # Create executor pool
        self._executor = ExecutorPool(
            worker_id=self.config.worker_id,
            max_concurrent=self.config.max_concurrent_tasks,
        )

        # Create result reporter
        self._reporter = ResultReporter(self.config)

        self._running = True
        logger.info("DAG listener started successfully")

    async def stop(self) -> None:
        """Stop listener and cleanup resources."""
        logger.info("Stopping DAG listener...")
        self._running = False

        if self._reporter:
            await self._reporter.close()
            self._reporter = None

        if self._receiver:
            await self._receiver.close()
            self._receiver = None

        if self._client:
            await self._client.close()
            self._client = None

        logger.info(
            f"DAG listener stopped. "
            f"Processed: {self._tasks_processed}, "
            f"Failed: {self._tasks_failed}"
        )

    async def run(self) -> None:
        """
        Main listener loop.

        Runs until stopped or shutdown requested.
        """
        if not self.config.enabled:
            logger.info("DAG listener disabled, not running")
            return

        await self.start()

        try:
            while self._running and not self._executor.shutdown_requested:
                await self._receive_batch()
        except Exception as e:
            logger.exception(f"DAG listener error: {e}")
            raise
        finally:
            await self.stop()

    async def _receive_batch(self) -> None:
        """Receive and process a batch of messages."""
        try:
            messages = await self._receiver.receive_messages(
                max_message_count=self.config.max_concurrent_tasks,
                max_wait_time=5,
            )

            if not messages:
                return

            logger.debug(f"Received {len(messages)} messages")

            # Process messages concurrently
            tasks = [
                self._process_message(msg)
                for msg in messages
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.exception(f"Error receiving messages: {e}")
            await asyncio.sleep(1)  # Brief pause before retry

    async def _process_message(self, message: ServiceBusReceivedMessage) -> None:
        """
        Process a single queue message.

        Args:
            message: Service Bus message
        """
        task: Optional[TaskMessage] = None

        try:
            # Parse message body
            body = json.loads(str(message))
            task = TaskMessage.from_queue_message(body)

            logger.info(
                f"Processing task {task.task_id}: "
                f"handler={task.handler}"
            )

            # Optionally report "running" status
            # await self._reporter.report_running(
            #     task.task_id, task.job_id, task.node_id
            # )

            # Execute task
            result = await self._executor.execute(task)

            # Report result to orchestrator
            reported = await self._reporter.report(result)

            if reported:
                # Complete message (remove from queue)
                await self._receiver.complete_message(message)
                self._tasks_processed += 1
                logger.info(f"Task {task.task_id} completed and acknowledged")
            else:
                # Abandon message (return to queue for retry)
                await self._receiver.abandon_message(message)
                self._tasks_failed += 1
                logger.warning(
                    f"Task {task.task_id} completed but callback failed, "
                    "message abandoned"
                )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid message JSON: {e}")
            # Dead-letter malformed messages
            await self._receiver.dead_letter_message(
                message,
                reason="InvalidJSON",
                error_description=str(e),
            )
            self._tasks_failed += 1

        except Exception as e:
            logger.exception(f"Error processing message: {e}")

            if task:
                # Try to report failure
                from .contracts import TaskStatus
                error_result = TaskResult(
                    task_id=task.task_id,
                    job_id=task.job_id,
                    node_id=task.node_id,
                    status=TaskStatus.FAILED,
                    error_message=f"Worker error: {e}",
                    worker_id=self.config.worker_id,
                )
                await self._reporter.report(error_result)

            # Abandon for retry
            await self._receiver.abandon_message(message)
            self._tasks_failed += 1

    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._running

    @property
    def stats(self) -> dict:
        """Get listener statistics."""
        return {
            "running": self._running,
            "tasks_processed": self._tasks_processed,
            "tasks_failed": self._tasks_failed,
            "active_tasks": self._executor.active_count if self._executor else 0,
        }


async def run_dag_listener(config: Optional[DagWorkerConfig] = None) -> None:
    """
    Convenience function to run the DAG listener.

    Args:
        config: Optional configuration (defaults to from_env)
    """
    if config is None:
        config = DagWorkerConfig.from_env()

    listener = DagListener(config)
    await listener.run()
