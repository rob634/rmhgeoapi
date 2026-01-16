# ============================================================================
# INFRASTRUCTURE PACKAGE - LAZY LOADING
# ============================================================================
# STATUS: Infrastructure - Repository pattern with Azure Functions cold start fix
# PURPOSE: Lazy import mechanism to defer env var reads until runtime ready
# LAST_REVIEWED: 14 JAN 2026
# ============================================================================
"""
Infrastructure Package - Lazy Loading Implementation.

Provides all repository implementations with lazy loading to prevent
premature initialization of singletons, loggers, and environment variable reads.

All imports are deferred until actually needed to avoid:
    - Premature environment variable access
    - Singleton initialization before configuration
    - Logger proliferation
    - Import order dependencies

Why Lazy Loading is Essential in Azure Functions:

The Azure Functions runtime has a specific initialization sequence:

    Cold Start -> Import Modules -> Runtime Init -> Ready for Triggers
         |              |                |               |
      ~500ms      NO ENV VARS!     ENV VARS SET    NOW SAFE TO USE

The Problem:
    - Azure Functions loads function_app.py on EVERY cold start
    - All top-level imports execute immediately during load
    - This happens BEFORE environment variables are guaranteed available
    - This happens BEFORE managed identity tokens are ready
    - This happens BEFORE the Functions runtime is fully initialized

What Happens Without Lazy Loading:
    - config.py imports and reads env vars immediately -> KeyError
    - Singletons initialize during import -> Missing configuration
    - DefaultAzureCredential tries to authenticate -> Auth failures
    - Database connections attempt during module load -> Connection refused
    Result: Mysterious failures that "work locally but fail in Azure"

What Happens With Our Lazy Loading:
    - function_app.py imports repositories package
    - repositories/__init__.py loads but DOESN'T import modules
    - Azure Functions runtime fully initializes
    - Environment variables become available
    - Managed identity tokens become ready
    - THEN your first HTTP/Queue trigger fires
    - ONLY NOW does config.py read environment variables
    - ONLY NOW do singletons initialize with proper config

How This Lazy Loading Works:
    - __getattr__ intercepts any access to repository classes
    - The actual import happens ONLY when the class is first used
    - This is typically when RepositoryFactory.create_repositories() is called
    - By then, Azure Functions runtime is fully initialized

Historical context archived in: docs/archive/INIT_PY_HISTORY.md
"""

from typing import TYPE_CHECKING

# For type checking only - doesn't actually import at runtime
if TYPE_CHECKING:
    from .factory import RepositoryFactory as _RepositoryFactory
    from .jobs_tasks import JobRepository as _JobRepository
    from .jobs_tasks import TaskRepository as _TaskRepository
    from .jobs_tasks import StageCompletionRepository as _StageCompletionRepository
    from .postgresql import PostgreSQLRepository as _PostgreSQLRepository
    from .base import BaseRepository as _BaseRepository
    from .blob import BlobRepository as _BlobRepository
    from .vault import VaultRepository as _VaultRepository
    from .platform import PlatformRepository as _PlatformRepository
    from .platform import ApiRequestRepository as _ApiRequestRepository
    from .h3_batch_tracking import H3BatchTracker as _H3BatchTracker
    from .interface_repository import (
        IJobRepository as _IJobRepository,
        ITaskRepository as _ITaskRepository,
        IBlobRepository as _IBlobRepository,
    )
    from .validators import (
        RESOURCE_VALIDATORS as _RESOURCE_VALIDATORS,
        run_validators as _run_validators,
        ValidatorResult as _ValidatorResult,
    )
    from .data_factory import AzureDataFactoryRepository as _AzureDataFactoryRepository
    from .interface_repository import IDataFactoryRepository as _IDataFactoryRepository
    from .curated_repository import CuratedDatasetRepository as _CuratedDatasetRepository
    from .curated_repository import CuratedUpdateLogRepository as _CuratedUpdateLogRepository
    from .promoted_repository import PromotedDatasetRepository as _PromotedDatasetRepository
    from .approval_repository import ApprovalRepository as _ApprovalRepository


def __getattr__(name: str):
    """
    Lazy import mechanism - only imports when actually accessed.
    This prevents module-level code execution until needed.
    """
    # Factory - most common import
    if name == "RepositoryFactory":
        from .factory import RepositoryFactory
        return RepositoryFactory

    # Job/Task repositories
    elif name == "JobRepository":
        from .jobs_tasks import JobRepository
        return JobRepository
    elif name == "TaskRepository":
        from .jobs_tasks import TaskRepository
        return TaskRepository
    elif name == "StageCompletionRepository":
        from .jobs_tasks import StageCompletionRepository
        return StageCompletionRepository

    # PostgreSQL repository
    elif name == "PostgreSQLRepository":
        from .postgresql import PostgreSQLRepository
        return PostgreSQLRepository

    # Base repository
    elif name == "BaseRepository":
        from .base import BaseRepository
        return BaseRepository

    # Blob repository
    elif name == "BlobRepository":
        from .blob import BlobRepository
        return BlobRepository

    # Vault repository
    elif name == "VaultRepository":
        from .vault import VaultRepository
        return VaultRepository

    # Platform repositories
    elif name == "PlatformRepository":
        from .platform import PlatformRepository
        return PlatformRepository
    elif name == "ApiRequestRepository":
        from .platform import ApiRequestRepository
        return ApiRequestRepository

    # H3 batch tracking
    elif name == "H3BatchTracker":
        from .h3_batch_tracking import H3BatchTracker
        return H3BatchTracker

    # Resource validators
    elif name == "RESOURCE_VALIDATORS":
        from .validators import RESOURCE_VALIDATORS
        return RESOURCE_VALIDATORS
    elif name == "run_validators":
        from .validators import run_validators
        return run_validators
    elif name == "ValidatorResult":
        from .validators import ValidatorResult
        return ValidatorResult

    # Interfaces
    elif name == "IJobRepository":
        from .interface_repository import IJobRepository
        return IJobRepository
    elif name == "ITaskRepository":
        from .interface_repository import ITaskRepository
        return ITaskRepository
    elif name == "IBlobRepository":
        from .interface_repository import IBlobRepository
        return IBlobRepository
    elif name == "IDataFactoryRepository":
        from .interface_repository import IDataFactoryRepository
        return IDataFactoryRepository

    # Azure Data Factory
    elif name == "AzureDataFactoryRepository":
        from .data_factory import AzureDataFactoryRepository
        return AzureDataFactoryRepository

    # Curated datasets
    elif name == "CuratedDatasetRepository":
        from .curated_repository import CuratedDatasetRepository
        return CuratedDatasetRepository
    elif name == "CuratedUpdateLogRepository":
        from .curated_repository import CuratedUpdateLogRepository
        return CuratedUpdateLogRepository

    # Promoted datasets
    elif name == "PromotedDatasetRepository":
        from .promoted_repository import PromotedDatasetRepository
        return PromotedDatasetRepository

    # Dataset approvals (F4.AP)
    elif name == "ApprovalRepository":
        from .approval_repository import ApprovalRepository
        return ApprovalRepository

    # Pipeline Observability (E13)
    elif name == "MetricsRepository":
        from .metrics_repository import MetricsRepository
        return MetricsRepository
    elif name == "JobProgressTracker":
        from .job_progress import JobProgressTracker
        return JobProgressTracker
    elif name == "JobProgressSnapshot":
        from .job_progress import JobProgressSnapshot
        return JobProgressSnapshot
    elif name == "H3AggregationTracker":
        from .job_progress_contexts import H3AggregationTracker
        return H3AggregationTracker
    elif name == "FathomETLTracker":
        from .job_progress_contexts import FathomETLTracker
        return FathomETLTracker
    elif name == "RasterCollectionTracker":
        from .job_progress_contexts import RasterCollectionTracker
        return RasterCollectionTracker

    # Helper function for getting default repositories
    elif name == "get_default_repositories":
        from .factory import get_default_repositories
        return get_default_repositories

    # Checkpoint Manager (Docker resume support)
    elif name == "CheckpointManager":
        from .checkpoint_manager import CheckpointManager
        return CheckpointManager
    elif name == "CheckpointValidationError":
        from .checkpoint_manager import CheckpointValidationError
        return CheckpointValidationError

    else:
        raise AttributeError(f"module 'infrastructure' has no attribute '{name}'")


# Define what's available for * imports (though we discourage using import *)
__all__ = [
    "RepositoryFactory",
    "JobRepository",
    "TaskRepository",
    "StageCompletionRepository",
    "PostgreSQLRepository",
    "BaseRepository",
    "BlobRepository",
    "VaultRepository",
    "PlatformRepository",
    "ApiRequestRepository",
    "H3BatchTracker",
    "RESOURCE_VALIDATORS",
    "run_validators",
    "ValidatorResult",
    "IJobRepository",
    "ITaskRepository",
    "IBlobRepository",
    "IDataFactoryRepository",
    "AzureDataFactoryRepository",
    "CuratedDatasetRepository",
    "CuratedUpdateLogRepository",
    "PromotedDatasetRepository",
    "ApprovalRepository",
    "MetricsRepository",
    "JobProgressTracker",
    "JobProgressSnapshot",
    "H3AggregationTracker",
    "FathomETLTracker",
    "RasterCollectionTracker",
    "get_default_repositories",
    "CheckpointManager",
    "CheckpointValidationError",
]
