# ============================================================================
# DAG WORKER MODULE
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - DAG task execution for workers
# PURPOSE: Listen for DAG tasks, execute handlers, report results
# CREATED: 29 JAN 2026
# ============================================================================
"""
DAG Worker Module

This module provides DAG task execution capabilities for the Docker worker.
It runs alongside the existing Epoch 4 worker, listening to a separate queue.

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    DOCKER WORKER                             │
    │                                                              │
    │   ┌─────────────────────┐    ┌─────────────────────┐        │
    │   │  Epoch 4 Listener   │    │   DAG Listener      │        │
    │   │  (epoch4-tasks)     │    │   (dag-worker-tasks)│        │
    │   └──────────┬──────────┘    └──────────┬──────────┘        │
    │              │                          │                    │
    │              └────────────┬─────────────┘                    │
    │                           ▼                                  │
    │              ┌───────────────────────┐                       │
    │              │   SHARED HANDLERS     │                       │
    │              │   (raster, vector,    │                       │
    │              │    stac, etc.)        │                       │
    │              └───────────────────────┘                       │
    └─────────────────────────────────────────────────────────────┘

Components:
    - listener.py:   Polls dag-worker-tasks queue for messages
    - executor.py:   Looks up and runs handler functions
    - reporter.py:   Reports results back to orchestrator
    - contracts.py:  Message schemas (TaskMessage, TaskResult)

Usage:
    from dag_worker import DagListener

    listener = DagListener(config)
    await listener.run()  # Runs until stopped

Configuration:
    Environment variables:
        DAG_QUEUE_ENABLED=true
        DAG_QUEUE_CONNECTION=<service bus connection string>
        DAG_QUEUE_NAME=dag-worker-tasks
        DAG_ORCHESTRATOR_URL=http://orchestrator:8000

Isolation:
    This module is designed to be completely self-contained.
    It can be copied to rmhdagmaster/worker/ once tested.
"""

from .listener import DagListener
from .executor import TaskExecutor
from .reporter import ResultReporter
from .contracts import TaskMessage, TaskResult, TaskStatus

__all__ = [
    "DagListener",
    "TaskExecutor",
    "ResultReporter",
    "TaskMessage",
    "TaskResult",
    "TaskStatus",
]
