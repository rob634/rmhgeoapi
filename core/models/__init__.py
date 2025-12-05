# ============================================================================
# CLAUDE CONTEXT - CORE MODELS PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core models - Pure data structures
# PURPOSE: Export all pure data models from the core.models package
# LAST_REVIEWED: 16 OCT 2025
# EXPORTS: All data models (JobRecord, TaskRecord, enums, contexts, results)
# INTERFACES: Package initialization only
# PYDANTIC_MODELS: Exported from submodules (job, task, enums, context, results)
# DEPENDENCIES: Core model submodules
# AZURE_FUNCTIONS: Required for package imports
# PATTERNS: Package initialization, Clean separation of concerns
# ENTRY_POINTS: from core.models import JobRecord, TaskRecord, JobStatus
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

# Platform models (simplified 22 NOV 2025 - thin tracking only)
from .platform import (
    ApiRequest,
    PlatformRequestStatus,
    DataType,
    OperationType,
    PlatformRequest
)
# NOTE: OrchestrationJob REMOVED (22 NOV 2025) - no job chaining in Platform

# Janitor models (21 NOV 2025)
from .janitor import (
    JanitorRun,
    JanitorRunType,
    JanitorRunStatus
)

# ETL tracking models (05 DEC 2025)
from .etl import (
    EtlFathomRecord
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
    'JobCompletionResult',

    # Platform models (simplified 22 NOV 2025 - thin tracking)
    'ApiRequest',
    'PlatformRequestStatus',
    'DataType',
    'OperationType',
    'PlatformRequest',
    # NOTE: OrchestrationJob REMOVED - no job chaining in Platform

    # Janitor models (21 NOV 2025)
    'JanitorRun',
    'JanitorRunType',
    'JanitorRunStatus',

    # ETL tracking models (05 DEC 2025)
    'EtlFathomRecord'
]