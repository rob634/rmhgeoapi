# ============================================================================
# DAG RESULT REPORTER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Report task results to orchestrator
# PURPOSE: POST task results to orchestrator callback endpoint
# CREATED: 29 JAN 2026
# ============================================================================
"""
DAG Result Reporter

Reports task results back to the orchestrator via HTTP callback.

The orchestrator exposes POST /api/v1/callbacks/task-result
which accepts TaskResult payloads.
"""

import logging
from typing import Optional

import httpx

from .contracts import TaskResult
from .config import DagWorkerConfig

logger = logging.getLogger(__name__)


class ResultReporter:
    """
    Reports task results to the orchestrator.

    Uses HTTP POST to the orchestrator's callback endpoint.
    Includes retry logic for transient failures.
    """

    def __init__(self, config: DagWorkerConfig):
        """
        Initialize reporter.

        Args:
            config: DAG worker configuration
        """
        self.config = config
        self.callback_url = config.callback_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.callback_timeout_seconds),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def report(self, result: TaskResult) -> bool:
        """
        Report a task result to the orchestrator.

        Args:
            result: TaskResult to report

        Returns:
            True if report succeeded, False otherwise
        """
        client = await self._get_client()

        logger.info(
            f"Reporting result for task {result.task_id}: "
            f"status={result.status.value}"
        )

        last_error = None

        for attempt in range(self.config.callback_retries):
            try:
                response = await client.post(
                    self.callback_url,
                    json=result.to_dict(),
                )

                if response.status_code in (200, 201, 202):
                    logger.info(
                        f"Result reported successfully for task {result.task_id}"
                    )
                    return True

                logger.warning(
                    f"Callback returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
                last_error = f"HTTP {response.status_code}"

            except httpx.TimeoutException as e:
                last_error = f"Timeout: {e}"
                logger.warning(
                    f"Callback timeout (attempt {attempt + 1}/"
                    f"{self.config.callback_retries}): {e}"
                )

            except httpx.RequestError as e:
                last_error = f"Request error: {e}"
                logger.warning(
                    f"Callback request failed (attempt {attempt + 1}/"
                    f"{self.config.callback_retries}): {e}"
                )

            except Exception as e:
                last_error = f"Unexpected error: {e}"
                logger.exception(
                    f"Unexpected callback error (attempt {attempt + 1}/"
                    f"{self.config.callback_retries}): {e}"
                )

        # All retries exhausted
        logger.error(
            f"Failed to report result for task {result.task_id} "
            f"after {self.config.callback_retries} attempts: {last_error}"
        )
        return False

    async def report_running(self, task_id: str, job_id: str, node_id: str) -> bool:
        """
        Report that a task is now running.

        This is optional - lets the orchestrator know work has started.

        Args:
            task_id: Task identifier
            job_id: Job identifier
            node_id: Node identifier

        Returns:
            True if report succeeded
        """
        from .contracts import TaskStatus

        result = TaskResult(
            task_id=task_id,
            job_id=job_id,
            node_id=node_id,
            status=TaskStatus.RUNNING,
            worker_id=self.config.worker_id,
        )

        return await self.report(result)

    async def __aenter__(self) -> "ResultReporter":
        await self._get_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
