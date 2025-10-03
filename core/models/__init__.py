# ============================================================================
# CLAUDE CONTEXT - CORE MODELS PACKAGE
# ============================================================================
# CATEGORY: DATA MODELS - DATABASE ENTITIES
# PURPOSE: Pydantic model mapping to PostgreSQL table/database structure
# EPOCH: Shared by all epochs (database schema)# PURPOSE: Export all pure data models from the core.models package
# EXPORTS: All data models and enums
# AZURE FUNCTIONS: Required for package imports
# ============================================================================

"""
Core data models package.

This package contains pure data structures without business logic.
All business logic is in the core.logic package.
"""

# Enums
from .enums import (
    JobStatus,
    TaskStatus,
    StageStatus
)

# Job models
from .job import JobRecord

# Task models
from .task import (
    TaskRecord,
    TaskDefinition
)

# Stage models
from .stage import Stage

# Context models
from .context import (
    JobExecutionContext,
    StageExecutionContext,
    TaskExecutionContext
)

# Result models
from .results import (
    TaskResult,
    StageResultContract,
    StageAdvancementResult,
    JobCompletionResult
)

__all__ = [
    # Enums
    'JobStatus',
    'TaskStatus',
    'StageStatus',

    # Job models
    'JobRecord',

    # Task models
    'TaskRecord',
    'TaskDefinition',

    # Stage models
    'Stage',

    # Context models
    'JobExecutionContext',
    'StageExecutionContext',
    'TaskExecutionContext',

    # Result models
    'TaskResult',
    'StageResultContract',
    'StageAdvancementResult',
    'JobCompletionResult'
]