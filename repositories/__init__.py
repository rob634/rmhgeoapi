# ============================================================================
# CLAUDE CONTEXT - REPOSITORY PACKAGE
# ============================================================================
# PURPOSE: Package initialization for repository modules with lazy imports
# EXPORTS: Factory and repository classes via lazy loading
# INTERFACES: All repository interfaces and implementations
# PYDANTIC_MODELS: None at package level - models in individual modules
# DEPENDENCIES: Individual repositories loaded on demand
# SOURCE: Module imports only when requested
# SCOPE: Application-wide repository access
# VALIDATION: Import validation handled per module
# PATTERNS: Lazy loading to prevent premature initialization
# ENTRY_POINTS: from repositories import RepositoryFactory
# INDEX: Lazy imports prevent module-level code execution
# ============================================================================

"""
Repository Package - Lazy Loading Implementation

This package provides all repository implementations with lazy loading
to prevent premature initialization of singletons, loggers, and
environment variable reads.

All imports are deferred until actually needed to avoid:
- Premature environment variable access
- Singleton initialization before configuration
- Logger proliferation
- Import order dependencies

Author: Robert and Geospatial Claude Legion
Date: 23 SEP 2025
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
    from .interface_repository import (
        IJobRepository as _IJobRepository,
        ITaskRepository as _ITaskRepository,
        IBlobRepository as _IBlobRepository,
    )


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

    # Helper function for getting default repositories
    elif name == "get_default_repositories":
        from .factory import get_default_repositories
        return get_default_repositories

    else:
        raise AttributeError(f"module 'repositories' has no attribute '{name}'")


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
    "IJobRepository",
    "ITaskRepository",
    "IBlobRepository",
    "get_default_repositories",
]