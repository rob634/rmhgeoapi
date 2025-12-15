"""
Core Data Models Package.

Contains pure data structures without business logic.
All business logic is in the core.logic package.

Exports:
    JobRecord, TaskRecord: Database models
    JobStatus, TaskStatus, StageStatus: Status enums
    JobExecutionContext, StageExecutionContext, TaskExecutionContext: Contexts
    TaskResult, StageResultContract: Result types
    ApiRequest, PlatformRequest: Platform models
    JanitorRun: Janitor maintenance models
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

# Unpublish audit models (12 DEC 2025)
from .unpublish import (
    UnpublishJobRecord,
    UnpublishType,
    UnpublishStatus
)

# Curated dataset models (15 DEC 2025)
from .curated import (
    CuratedDataset,
    CuratedUpdateLog,
    CuratedSourceType,
    CuratedUpdateStrategy,
    CuratedUpdateType,
    CuratedUpdateStatus
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
    'EtlFathomRecord',

    # Unpublish audit models (12 DEC 2025)
    'UnpublishJobRecord',
    'UnpublishType',
    'UnpublishStatus',

    # Curated dataset models (15 DEC 2025)
    'CuratedDataset',
    'CuratedUpdateLog',
    'CuratedSourceType',
    'CuratedUpdateStrategy',
    'CuratedUpdateType',
    'CuratedUpdateStatus'
]