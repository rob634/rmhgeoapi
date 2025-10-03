# ============================================================================
# CLAUDE CONTEXT - CORE MODELS - ENUMS
# ============================================================================
# CATEGORY: DATA MODELS - DATABASE ENTITIES
# PURPOSE: Pydantic model mapping to PostgreSQL table/database structure
# EPOCH: Shared by all epochs (database schema)# PURPOSE: Pure enum definitions for job and task states
# EXPORTS: JobStatus, TaskStatus, StageStatus enums
# INTERFACES: Standard Python Enum
# PYDANTIC_MODELS: None - pure enums only
# DEPENDENCIES: enum
# SOURCE: Extracted from schema_base.py
# SCOPE: Core data model enumerations
# VALIDATION: Enum membership only
# PATTERNS: Enum pattern for type safety
# ENTRY_POINTS: from core.models.enums import JobStatus, TaskStatus
# ============================================================================

"""
Pure enumeration types for the core framework.

These enums define valid states for jobs, tasks, and stages.
No business logic - just pure type definitions.
"""

from enum import Enum


class JobStatus(Enum):
    """
    Valid status values for jobs.

    State transitions:
    - QUEUED -> PROCESSING -> COMPLETED
    - QUEUED -> PROCESSING -> FAILED
    - QUEUED -> PROCESSING -> COMPLETED_WITH_ERRORS
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


class TaskStatus(Enum):
    """
    Valid status values for tasks.

    State transitions:
    - QUEUED -> PROCESSING -> COMPLETED
    - QUEUED -> PROCESSING -> FAILED
    - QUEUED -> PROCESSING -> FAILED -> RETRYING -> PROCESSING
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    PENDING_RETRY = "pending_retry"  # Waiting for retry
    CANCELLED = "cancelled"  # Task was cancelled


class StageStatus(Enum):
    """
    Valid status values for stages within a job.

    These are derived from task statuses but tracked separately
    for stage-level orchestration.
    """

    PENDING = "pending"  # Stage not yet started
    PROCESSING = "processing"  # Stage has active tasks
    COMPLETED = "completed"  # All tasks in stage completed
    FAILED = "failed"  # Stage failed (unrecoverable)
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # Some tasks failed but stage continues