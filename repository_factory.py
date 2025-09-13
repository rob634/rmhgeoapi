# ============================================================================
# CLAUDE CONTEXT - FACTORY
# ============================================================================
# PURPOSE: Central factory for creating all repository instances across different storage backends
# EXPORTS: RepositoryFactory
# INTERFACES: Factory pattern for repository instantiation
# PYDANTIC_MODELS: None - returns repository instances
# DEPENDENCIES: repository_jobs_tasks, repository_vault, typing
# SOURCE: Configuration from AppConfig or environment variables
# SCOPE: Global repository creation for entire application
# VALIDATION: Connection validation handled by individual repositories
# PATTERNS: Factory pattern, Abstract Factory (future: multiple backends)
# ENTRY_POINTS: repos = RepositoryFactory.create_repositories(); job_repo = repos['job_repo']
# INDEX: RepositoryFactory:45, create_repositories:65, create_job_repository:107
# ============================================================================

"""
Repository Factory - Central Creation Point

This module provides the factory for creating all repository instances.
It serves as the single point for repository instantiation, allowing
easy extension to support multiple storage backends in the future.

Current Support:
- PostgreSQL repositories (jobs, tasks, completion detection)
- Vault repository (when enabled)

Future Support:
- Blob storage repositories
- Cosmos DB repositories
- Redis cache repositories

Author: Robert and Geospatial Claude Legion
Date: 10 September 2025
"""

# Imports at top for fast failure
from typing import Dict, Any, Optional
import logging

from repository_jobs_tasks import JobRepository, TaskRepository, CompletionDetector
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "RepositoryFactory")


# ============================================================================
# REPOSITORY FACTORY - Central creation point
# ============================================================================

class RepositoryFactory:
    """
    Factory for creating repository instances.
    
    This is the central factory that creates all repository types.
    Currently supports PostgreSQL repositories, with future support
    for blob storage, Cosmos DB, and other backends.
    
    Design Philosophy:
    - Single factory for all repository types
    - Clean extension point for new storage backends
    - Configuration-driven repository selection
    - Consistent interface across all storage types
    """
    
    @staticmethod
    def create_repositories(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> Dict[str, Any]:
        """
        Create all repository instances for job/task management.
        
        This is the primary factory method used throughout the application
        to get repository instances. It creates all three core repositories
        needed for job and task management.
        
        Args:
            connection_string: PostgreSQL connection string (uses env if not provided)
            schema_name: Database schema name (default: "app")
            
        Returns:
            Dictionary with job_repo, task_repo, and completion_detector
            
        Example:
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']
            task_repo = repos['task_repo']
            completion = repos['completion_detector']
        """
        logger.info("🏭 Creating PostgreSQL repositories")
        logger.debug(f"  Connection string provided: {connection_string is not None}")
        logger.debug(f"  Schema name: {schema_name}")
        
        # Create repositories
        logger.debug("📦 Creating JobRepository...")
        job_repo = JobRepository(connection_string, schema_name)
        logger.debug("📦 Creating TaskRepository...")
        task_repo = TaskRepository(connection_string, schema_name)
        logger.debug("📦 Creating CompletionDetector...")
        completion_detector = CompletionDetector(connection_string, schema_name)
        
        logger.info("✅ All repositories created successfully")
        
        return {
            'job_repo': job_repo,
            'task_repo': task_repo,
            'completion_detector': completion_detector
        }
    
    @staticmethod
    def create_job_repository(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> JobRepository:
        """
        Create only a job repository instance.
        
        Use this when you only need job operations without tasks.
        
        Args:
            connection_string: PostgreSQL connection string
            schema_name: Database schema name
            
        Returns:
            JobRepository instance
        """
        return JobRepository(connection_string, schema_name)
    
    @staticmethod
    def create_task_repository(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> TaskRepository:
        """
        Create only a task repository instance.
        
        Use this when you only need task operations without jobs.
        
        Args:
            connection_string: PostgreSQL connection string
            schema_name: Database schema name
            
        Returns:
            TaskRepository instance
        """
        return TaskRepository(connection_string, schema_name)
    
    @staticmethod
    def create_completion_detector(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> CompletionDetector:
        """
        Create only a completion detector instance.
        
        Use this for atomic completion detection operations.
        
        Args:
            connection_string: PostgreSQL connection string
            schema_name: Database schema name
            
        Returns:
            CompletionDetector instance
        """
        return CompletionDetector(connection_string, schema_name)
    
    # ========================================================================
    # FUTURE REPOSITORY TYPES
    # ========================================================================
    
    @staticmethod
    def create_blob_repository(
        storage_account: Optional[str] = None,
        use_default_credential: bool = True,
        connection_string: Optional[str] = None
    ) -> 'BlobRepository':
        """
        Create blob storage repository with authentication.
        
        This is THE centralized authentication point for all blob operations.
        Uses DefaultAzureCredential for seamless auth across environments.
        
        Args:
            storage_account: Storage account name (uses env if not provided)
            use_default_credential: Use DefaultAzureCredential (True) or connection string (False)
            connection_string: Optional connection string (alternative to DefaultAzureCredential)
            
        Returns:
            BlobRepository singleton instance
            
        Example:
            # Recommended usage
            blob_repo = RepositoryFactory.create_blob_repository()
            
            # With specific account
            blob_repo = RepositoryFactory.create_blob_repository(
                storage_account="myaccount"
            )
        """
        from repository_blob import BlobRepository
        
        logger.info("🏭 Creating Blob Storage repository")
        logger.debug(f"  Storage account: {storage_account or 'from environment'}")
        logger.debug(f"  Use DefaultAzureCredential: {use_default_credential}")
        
        # Create repository based on authentication method
        if connection_string:
            blob_repo = BlobRepository.instance(connection_string=connection_string)
        else:
            blob_repo = BlobRepository.instance(storage_account=storage_account)
        
        logger.info("✅ Blob repository created successfully")
        return blob_repo
    
    @staticmethod
    def create_cosmos_repository(
        account_url: Optional[str] = None,
        database_name: Optional[str] = None
    ) -> Any:
        """
        Future: Create Cosmos DB repository.
        
        This will create repositories for Cosmos DB operations
        when implemented.
        """
        raise NotImplementedError(
            "Cosmos DB repository not yet implemented. "
            "This is a placeholder for future functionality."
        )
    
    @staticmethod
    def create_vault_repository() -> Any:
        """
        Create Azure Key Vault repository (currently disabled).
        
        Returns:
            VaultRepository instance when RBAC is configured
            
        Raises:
            NotImplementedError: Until Key Vault RBAC is set up
        """
        # When ready to enable:
        # from repository_vault import VaultRepository, VaultRepositoryFactory
        # return VaultRepositoryFactory.create_with_config()
        
        raise NotImplementedError(
            "Vault repository is disabled pending RBAC configuration. "
            "See repository_vault.py for implementation details."
        )


# ============================================================================
# FACTORY HELPERS
# ============================================================================

def get_default_repositories() -> Dict[str, Any]:
    """
    Convenience function to get default repository set.
    
    This is a helper for the most common use case - getting all three
    core repositories with default configuration.
    
    Returns:
        Dictionary with job_repo, task_repo, and completion_detector
    """
    return RepositoryFactory.create_repositories()


# Export the main factory
__all__ = ['RepositoryFactory', 'get_default_repositories']