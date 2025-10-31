# ============================================================================
# CLAUDE CONTEXT - INFRASTRUCTURE PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - Repository and service layer
# PURPOSE: Package initialization for repository modules with lazy imports
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: Factory and repository classes via lazy loading
# INTERFACES: All repository interfaces and implementations
# PYDANTIC_MODELS: None at package level - models in individual modules
# DEPENDENCIES: Individual repositories loaded on demand
# SOURCE: Module imports only when requested
# SCOPE: Application-wide repository access
# VALIDATION: Import validation handled per module
# PATTERNS: Lazy loading to prevent premature initialization
# ENTRY_POINTS: from infrastructure import RepositoryFactory
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

========================================================================
🎯 CRITICAL AZURE FUNCTIONS RUNTIME EXPLANATION (Learning Project Note)
========================================================================

WHY LAZY LOADING IS ESSENTIAL IN AZURE FUNCTIONS:

The Azure Functions runtime has a "mysterious" initialization sequence that
can cause failures if you don't understand it. Here's what actually happens:

1. COLD START SEQUENCE:
   Cold Start → Import Modules → Runtime Init → Ready for Triggers
        ↓             ↓                ↓              ↓
     ~500ms      NO ENV VARS!    ENV VARS SET   NOW SAFE TO USE

2. THE PROBLEM:
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

Author: Robert and Geospatial Claude Legion
Date: 23 SEP 2025
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
    from .platform import PlatformStatusRepository as _PlatformStatusRepository
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

    # Platform repositories
    elif name == "PlatformRepository":
        from .platform import PlatformRepository
        return PlatformRepository
    elif name == "PlatformStatusRepository":
        from .platform import PlatformStatusRepository
        return PlatformStatusRepository

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
    "PlatformStatusRepository",
    "IJobRepository",
    "ITaskRepository",
    "IBlobRepository",
    "get_default_repositories",
]