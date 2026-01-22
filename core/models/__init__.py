# ============================================================================
# CORE DATA MODELS PACKAGE
# ============================================================================
# STATUS: Core - Pure data structures without business logic
# PURPOSE: Export all data models (enums, records, contexts, results)
# LAST_REVIEWED: 14 JAN 2026
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
    VectorMetadata, RasterMetadata: Unified metadata models
    CogMetadataRecord: COG metadata tracking

Historical context archived in: docs/archive/INIT_PY_HISTORY.md
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
    ProcessVectorStage1Data,
    ProcessVectorStage1Result,
    ProcessVectorStage2Result
)

# Platform models
from .platform import (
    ApiRequest,
    PlatformRequestStatus,
    DataType,
    OperationType,
    PlatformRequest
)

# Janitor models
from .janitor import (
    JanitorRun,
    JanitorRunType,
    JanitorRunStatus
)

# ETL tracking models
from .etl import (
    EtlSourceFile
)

# Unpublish audit models
from .unpublish import (
    UnpublishJobRecord,
    UnpublishType,
    UnpublishStatus
)

# Curated dataset models
from .curated import (
    CuratedDataset,
    CuratedUpdateLog,
    CuratedSourceType,
    CuratedUpdateStrategy,
    CuratedUpdateType,
    CuratedUpdateStatus
)

# Promoted dataset models
from .promoted import (
    PromotedDataset,
    PromotedDatasetType,
    SystemRole,
    Classification
)

# System snapshot models
from .system_snapshot import (
    SystemSnapshotRecord,
    SnapshotTriggerType
)

# Unified metadata models (F7.8)
from .unified_metadata import (
    ProviderRole,
    Provider,
    SpatialExtent,
    TemporalExtent,
    Extent,
    BaseMetadata,
    VectorMetadata,
    RasterMetadata
)

# External references models (F7.8)
from .external_refs import (
    DataType as ExternalDataType,
    DDHRefs,
    ExternalRefs,
    DatasetRef,
    DatasetRefRecord
)

# Raster metadata models (F7.9)
from .raster_metadata import (
    CogMetadataRecord
)

# Dataset approval models (F4.AP)
from .approval import (
    DatasetApproval,
    ApprovalStatus
)

# Artifact registry models (20 JAN 2026)
from .artifact import (
    Artifact,
    ArtifactStatus
)

# External service registry models (22 JAN 2026)
from .external_service import (
    ExternalService,
    ServiceType,
    ServiceStatus
)

# Geo schema models - Service Layer (21 JAN 2026 - F7.IaC)
from .geo import (
    GeoTableCatalog,
    FeatureCollectionStyles  # OGC API Styles (22 JAN 2026)
)

# ETL tracking models - Internal App Schema (21 JAN 2026 - F7.IaC)
from .etl_tracking import (
    VectorEtlTracking,
    RasterEtlTracking,
    EtlStatus
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
    'ProcessVectorStage1Data',
    'ProcessVectorStage1Result',
    'ProcessVectorStage2Result',

    # Platform models
    'ApiRequest',
    'PlatformRequestStatus',
    'DataType',
    'OperationType',
    'PlatformRequest',

    # Janitor models
    'JanitorRun',
    'JanitorRunType',
    'JanitorRunStatus',

    # ETL tracking models
    'EtlSourceFile',

    # Unpublish audit models
    'UnpublishJobRecord',
    'UnpublishType',
    'UnpublishStatus',

    # Curated dataset models
    'CuratedDataset',
    'CuratedUpdateLog',
    'CuratedSourceType',
    'CuratedUpdateStrategy',
    'CuratedUpdateType',
    'CuratedUpdateStatus',

    # Promoted dataset models
    'PromotedDataset',
    'PromotedDatasetType',
    'SystemRole',
    'Classification',

    # System snapshot models
    'SystemSnapshotRecord',
    'SnapshotTriggerType',

    # Unified metadata models (F7.8)
    'ProviderRole',
    'Provider',
    'SpatialExtent',
    'TemporalExtent',
    'Extent',
    'BaseMetadata',
    'VectorMetadata',
    'RasterMetadata',

    # External references models (F7.8)
    'ExternalDataType',
    'DDHRefs',
    'ExternalRefs',
    'DatasetRef',
    'DatasetRefRecord',

    # Raster metadata models (F7.9)
    'CogMetadataRecord',

    # Dataset approval models (F4.AP)
    'DatasetApproval',
    'ApprovalStatus',

    # Artifact registry models (20 JAN 2026)
    'Artifact',
    'ArtifactStatus',

    # External service registry models (22 JAN 2026)
    'ExternalService',
    'ServiceType',
    'ServiceStatus',

    # Geo schema models - Service Layer (21 JAN 2026 - F7.IaC)
    'GeoTableCatalog',
    'FeatureCollectionStyles',  # OGC API Styles (22 JAN 2026)

    # ETL tracking models - Internal App Schema (21 JAN 2026 - F7.IaC)
    'VectorEtlTracking',
    'RasterEtlTracking',
    'EtlStatus',
]
