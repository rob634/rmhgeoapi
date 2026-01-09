# ============================================================================
# CORE DATA MODELS PACKAGE
# ============================================================================
# STATUS: Core - Pure data structures without business logic
# PURPOSE: Export all data models (enums, records, contexts, results)
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
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
    JobCompletionResult,
    # GAP-006 FIX (15 DEC 2025): Process vector stage result validation models
    ProcessVectorStage1Data,
    ProcessVectorStage1Result,
    ProcessVectorStage2Result
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

# ETL tracking models (21 DEC 2025 - generalized)
from .etl import (
    EtlSourceFile
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

# Promoted dataset models (23 DEC 2025)
from .promoted import (
    PromotedDataset,
    PromotedDatasetType,
    SystemRole,
    Classification
)

# System snapshot models (04 JAN 2026)
from .system_snapshot import (
    SystemSnapshotRecord,
    SnapshotTriggerType
)

# Unified metadata models (09 JAN 2026 - F7.8)
from .unified_metadata import (
    ProviderRole,
    Provider,
    SpatialExtent,
    TemporalExtent,
    Extent,
    BaseMetadata,
    VectorMetadata
)

# External references models (09 JAN 2026 - F7.8)
from .external_refs import (
    DataType as ExternalDataType,  # Avoid conflict with platform.DataType
    DDHRefs,
    ExternalRefs,
    DatasetRef,
    DatasetRefRecord
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
    # GAP-006 FIX (15 DEC 2025)
    'ProcessVectorStage1Data',
    'ProcessVectorStage1Result',
    'ProcessVectorStage2Result',

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

    # ETL tracking models (21 DEC 2025 - generalized)
    'EtlSourceFile',

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
    'CuratedUpdateStatus',

    # Promoted dataset models (23 DEC 2025)
    'PromotedDataset',
    'PromotedDatasetType',
    'SystemRole',
    'Classification',

    # System snapshot models (04 JAN 2026)
    'SystemSnapshotRecord',
    'SnapshotTriggerType',

    # Unified metadata models (09 JAN 2026 - F7.8)
    'ProviderRole',
    'Provider',
    'SpatialExtent',
    'TemporalExtent',
    'Extent',
    'BaseMetadata',
    'VectorMetadata',

    # External references models (09 JAN 2026 - F7.8)
    'ExternalDataType',
    'DDHRefs',
    'ExternalRefs',
    'DatasetRef',
    'DatasetRefRecord'
]