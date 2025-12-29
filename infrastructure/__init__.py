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

3. WHAT HAPPENS WITHOUT LAZY LOADING:
   ❌ config.py imports and reads env vars immediately → KeyError
   ❌ Singletons initialize during import → Missing configuration
   ❌ DefaultAzureCredential tries to authenticate → Auth failures
   ❌ Database connections attempt during module load → Connection refused
   Result: Mysterious failures that "work locally but fail in Azure"

4. WHAT HAPPENS WITH OUR LAZY LOADING:
   ✅ function_app.py imports repositories package
   ✅ repositories/__init__.py loads but DOESN'T import modules
   ✅ Azure Functions runtime fully initializes
   ✅ Environment variables become available
   ✅ Managed identity tokens become ready
   ✅ THEN your first HTTP/Queue trigger fires
   ✅ ONLY NOW does config.py read environment variables
   ✅ ONLY NOW do singletons initialize with proper config

5. COMMON SYMPTOMS WE'RE AVOIDING:
   • "Works locally but fails in Azure"
   • "Environment variable not found" (but it's definitely set)
   • "DefaultAzureCredential failed" during cold starts
   • "Connection refused" to services that should be available
   • "Works after warm-up but fails on first request"

6. HOW THIS LAZY LOADING WORKS:
   - __getattr__ intercepts any access to repository classes
   - The actual import happens ONLY when the class is first used
   - This is typically when RepositoryFactory.create_repositories() is called
   - By then, Azure Functions runtime is fully initialized

THIS IS A LEARNING PROJECT NOTE:
This explanation documents our understanding of Azure Functions' runtime
behavior through trial and error. The "mysterious" part is that there's
a gap between when Python starts importing modules and when the Functions
host has fully initialized the environment. Our lazy loading pattern
elegantly bridges this gap!

Updated: 27 SEP 2025 - Added Azure Functions runtime explanation
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
    # NOTE: PlatformStatusRepository REMOVED (22 NOV 2025) - thin tracking pattern
    from .h3_batch_tracking import H3BatchTracker as _H3BatchTracker
    from .interface_repository import (
        IJobRepository as _IJobRepository,
        ITaskRepository as _ITaskRepository,
        IBlobRepository as _IBlobRepository,
    )
    # Resource validators (28 NOV 2025 - pre-flight validation)
    from .validators import (
        RESOURCE_VALIDATORS as _RESOURCE_VALIDATORS,
        run_validators as _run_validators,
        ValidatorResult as _ValidatorResult,
    )
    # Azure Data Factory (29 NOV 2025 - ADF pipeline orchestration)
    from .data_factory import AzureDataFactoryRepository as _AzureDataFactoryRepository
    from .interface_repository import IDataFactoryRepository as _IDataFactoryRepository
    # Curated datasets (15 DEC 2025 - system-managed data)
    from .curated_repository import CuratedDatasetRepository as _CuratedDatasetRepository
    from .curated_repository import CuratedUpdateLogRepository as _CuratedUpdateLogRepository
    # Promoted datasets (23 DEC 2025 - gallery/system-reserved datasets)
    from .promoted_repository import PromotedDatasetRepository as _PromotedDatasetRepository


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

    # Platform repositories (simplified 22 NOV 2025 - thin tracking)
    elif name == "PlatformRepository":
        from .platform import PlatformRepository
        return PlatformRepository
    elif name == "ApiRequestRepository":
        from .platform import ApiRequestRepository
        return ApiRequestRepository
    # NOTE: PlatformStatusRepository REMOVED - use ApiRequestRepository instead

    # H3 batch tracking (26 NOV 2025 - idempotency framework)
    elif name == "H3BatchTracker":
        from .h3_batch_tracking import H3BatchTracker
        return H3BatchTracker

    # Resource validators (28 NOV 2025 - pre-flight validation)
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

    # Azure Data Factory (29 NOV 2025 - ADF pipeline orchestration)
    elif name == "AzureDataFactoryRepository":
        from .data_factory import AzureDataFactoryRepository
        return AzureDataFactoryRepository

    # Curated datasets (15 DEC 2025 - system-managed data)
    elif name == "CuratedDatasetRepository":
        from .curated_repository import CuratedDatasetRepository
        return CuratedDatasetRepository
    elif name == "CuratedUpdateLogRepository":
        from .curated_repository import CuratedUpdateLogRepository
        return CuratedUpdateLogRepository

    # Promoted datasets (23 DEC 2025 - gallery/system-reserved datasets)
    elif name == "PromotedDatasetRepository":
        from .promoted_repository import PromotedDatasetRepository
        return PromotedDatasetRepository

    # Pipeline Observability (28 DEC 2025 - E13)
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
    # NOTE: PlatformStatusRepository REMOVED (22 NOV 2025)
    "H3BatchTracker",  # Added 26 NOV 2025 - idempotency framework
    # Resource validators (28 NOV 2025 - pre-flight validation)
    "RESOURCE_VALIDATORS",
    "run_validators",
    "ValidatorResult",
    "IJobRepository",
    "ITaskRepository",
    "IBlobRepository",
    "IDataFactoryRepository",
    "AzureDataFactoryRepository",  # Added 29 NOV 2025 - ADF pipeline orchestration
    "CuratedDatasetRepository",  # Added 15 DEC 2025 - system-managed data
    "CuratedUpdateLogRepository",  # Added 15 DEC 2025 - system-managed data
    "PromotedDatasetRepository",  # Added 23 DEC 2025 - gallery/system-reserved datasets
    # Pipeline Observability (28 DEC 2025 - E13)
    "MetricsRepository",
    "JobProgressTracker",
    "JobProgressSnapshot",
    "H3AggregationTracker",
    "FathomETLTracker",
    "RasterCollectionTracker",
    "get_default_repositories",
]