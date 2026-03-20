# ============================================================================
# CLAUDE CONTEXT - WORKFLOW ENUMS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Enum definitions for DAG workflow nodes
# PURPOSE: Define NodeType, AggregationMode, and BackoffStrategy enums for workflow definitions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: NodeType, AggregationMode, BackoffStrategy, WorkflowRunStatus, WorkflowTaskStatus, ScheduleStatus
# DEPENDENCIES: enum
# ============================================================================

from enum import Enum


class NodeType(str, Enum):
    """Type discriminator for workflow DAG nodes."""
    TASK = "task"
    CONDITIONAL = "conditional"
    FAN_OUT = "fan_out"
    FAN_IN = "fan_in"


class AggregationMode(str, Enum):
    """How a fan-in node combines results from upstream parallel tasks."""
    COLLECT = "collect"
    CONCAT = "concat"
    SUM = "sum"
    FIRST = "first"
    LAST = "last"


class BackoffStrategy(str, Enum):
    """Retry backoff strategy for task retries."""
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


class WorkflowRunStatus(str, Enum):
    """Status of a workflow run (replaces JobStatus for DAG workflows)."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowTaskStatus(str, Enum):
    """
    Status of a workflow task instance.

    Transitions:
        pending  -> ready     (orchestrator: all deps satisfied)
        pending  -> skipped   (orchestrator: when clause false, or conditional untaken branch)
        ready    -> running   (worker: claimed via SKIP LOCKED)
        ready    -> expanded  (orchestrator: fan-out template, N child instances created)
        running  -> completed (worker: handler returned success)
        running  -> failed    (worker: handler returned failure or exception)
        running  -> ready     (janitor: stale heartbeat, retry_count < max)
        failed   -> ready     (manual: retry via admin endpoint)
    """
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    EXPANDED = "expanded"
    CANCELLED = "cancelled"


class ScheduleStatus(str, Enum):
    """Status of a scheduled workflow execution."""
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
