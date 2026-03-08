# ============================================================================
# DAG WORKER CONFIGURATION
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Environment-based configuration
# PURPOSE: Centralize DAG worker configuration
# CREATED: 29 JAN 2026
# ============================================================================
"""
DAG Worker Configuration

All configuration loaded from environment variables.
"""

import os
import socket
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DagWorkerConfig:
    """
    Configuration for the DAG worker.

    Loaded from environment variables at startup.
    """
    # Feature flag - enables/disables DAG listener
    enabled: bool = False

    # Service Bus connection
    queue_connection: str = ""
    queue_name: str = "dag-worker-tasks"

    # Orchestrator callback
    callback_url: str = ""

    # Worker identity
    worker_id: str = field(default_factory=lambda: socket.gethostname())

    # Execution settings
    max_concurrent_tasks: int = 1
    shutdown_timeout_seconds: int = 30

    # Retry settings for HTTP callbacks
    callback_retries: int = 3
    callback_timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "DagWorkerConfig":
        """
        Load configuration from environment variables.

        Environment Variables:
            DAG_QUEUE_ENABLED: Enable DAG listener (true/false)
            DAG_QUEUE_CONNECTION: Service Bus connection string
            DAG_QUEUE_NAME: Queue name (default: dag-worker-tasks)
            DAG_ORCHESTRATOR_CALLBACK_URL: Orchestrator callback endpoint
            DAG_WORKER_ID: Worker identifier (default: hostname)
            DAG_MAX_CONCURRENT_TASKS: Max parallel tasks (default: 1)
        """
        enabled_str = os.environ.get("DAG_QUEUE_ENABLED", "false").lower()
        enabled = enabled_str in ("true", "1", "yes")

        return cls(
            enabled=enabled,
            queue_connection=os.environ.get("DAG_QUEUE_CONNECTION", ""),
            queue_name=os.environ.get("DAG_QUEUE_NAME", "dag-worker-tasks"),
            callback_url=os.environ.get(
                "DAG_ORCHESTRATOR_CALLBACK_URL",
                "http://localhost:8000/api/v1/callbacks/task-result"
            ),
            worker_id=os.environ.get("DAG_WORKER_ID", socket.gethostname()),
            max_concurrent_tasks=int(os.environ.get("DAG_MAX_CONCURRENT_TASKS", "1")),
            shutdown_timeout_seconds=int(os.environ.get("DAG_SHUTDOWN_TIMEOUT", "30")),
        )

    def validate(self) -> list[str]:
        """
        Validate configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if self.enabled:
            if not self.queue_connection:
                errors.append("DAG_QUEUE_CONNECTION is required when DAG_QUEUE_ENABLED=true")
            if not self.callback_url:
                errors.append("DAG_ORCHESTRATOR_CALLBACK_URL is required when DAG_QUEUE_ENABLED=true")

        return errors

    @property
    def is_valid(self) -> bool:
        """Check if configuration is valid."""
        return len(self.validate()) == 0
