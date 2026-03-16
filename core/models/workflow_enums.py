# ============================================================================
# CLAUDE CONTEXT - WORKFLOW ENUMS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Enum definitions for DAG workflow nodes
# PURPOSE: Define NodeType, AggregationMode, and BackoffStrategy enums for workflow definitions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: NodeType, AggregationMode, BackoffStrategy
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
