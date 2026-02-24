# ============================================================================
# REPOSITORY FACTORY
# ============================================================================
# STATUS: Infrastructure - Central factory for all repository instantiation
# PURPOSE: Single point of repository creation with configuration injection
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Repository Factory.

Central factory for creating all repository instances. Serves as the single
point for repository instantiation, allowing easy extension to support
multiple storage backends.

Current Support:
    - PostgreSQL repositories (jobs, tasks, completion detection)
    - Vault repository (when enabled)

Future Support:
    - Blob storage repositories
    - Cosmos DB repositories
    - Redis cache repositories

Exports:
    RepositoryFactory: Static class with factory methods for all repository types
"""

# Imports at top for fast failure
from typing import Dict, Any, Optional
import logging

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
        from .jobs_tasks import JobRepository, TaskRepository, StageCompletionRepository

        logger.info("🏭 Creating PostgreSQL repositories")
        logger.debug(f"  Connection string provided: {connection_string is not None}")
        logger.debug(f"  Schema name: {schema_name}")

        # Create repositories
        logger.debug("📦 Creating JobRepository...")
        job_repo = JobRepository(connection_string, schema_name)
        logger.debug("📦 Creating TaskRepository...")
        task_repo = TaskRepository(connection_string, schema_name)
        logger.debug("📦 Creating StageCompletionRepository...")
        stage_completion_repo = StageCompletionRepository(connection_string, schema_name)
        
        logger.info("✅ All repositories created successfully")
        
        return {
            'job_repo': job_repo,
            'task_repo': task_repo,
            'stage_completion_repo': stage_completion_repo
        }
    
    @staticmethod
    def create_job_repository(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> 'JobRepository':
        """
        Create only a job repository instance.

        Use this when you only need job operations without tasks.

        Args:
            connection_string: PostgreSQL connection string
            schema_name: Database schema name

        Returns:
            JobRepository instance
        """
        from .jobs_tasks import JobRepository
        return JobRepository(connection_string, schema_name)
    
    @staticmethod
    def create_task_repository(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> 'TaskRepository':
        """
        Create only a task repository instance.

        Use this when you only need task operations without jobs.

        Args:
            connection_string: PostgreSQL connection string
            schema_name: Database schema name

        Returns:
            TaskRepository instance
        """
        from .jobs_tasks import TaskRepository
        return TaskRepository(connection_string, schema_name)
    
    @staticmethod
    def create_completion_detector(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> 'StageCompletionRepository':
        """
        Create only a completion detector instance.

        Use this for atomic completion detection operations.

        Args:
            connection_string: PostgreSQL connection string
            schema_name: Database schema name

        Returns:
            StageCompletionRepository instance
        """
        from .jobs_tasks import StageCompletionRepository
        return StageCompletionRepository(connection_string, schema_name)
    
    # ========================================================================
    # SERVICE BUS REPOSITORY
    # ========================================================================

    @staticmethod
    def create_service_bus_repository() -> 'ServiceBusRepository':
        """
        Create Service Bus repository for message queue operations.

        Uses Azure Service Bus for all async job/task messaging.
        Singleton pattern ensures credentials created once per worker.

        Returns:
            ServiceBusRepository singleton instance

        Example:
            repo = RepositoryFactory.create_service_bus_repository()
            repo.send_message("geospatial-jobs", job_message)
        """
        from .service_bus import ServiceBusRepository

        logger.info("🚌 Creating Service Bus repository")
        service_bus_repo = ServiceBusRepository.instance()
        logger.info("✅ Service Bus repository created successfully")

        return service_bus_repo

    @staticmethod
    def create_blob_repository(
        zone: str = "silver",
        storage_account: Optional[str] = None,
        use_default_credential: bool = True,
        connection_string: Optional[str] = None
    ) -> 'BlobRepository':
        """
        Create blob storage repository for specific trust zone.

        This is THE centralized authentication point for all blob operations.
        Uses DefaultAzureCredential for seamless auth across environments.

        Multi-Account Pattern (NEW - 29 OCT 2025):
        - Bronze: Untrusted user uploads (read-only for ETL)
        - Silver: Trusted processed data (ETL read-write, REST API read-only)
        - SilverExternal: Airgapped replica (ETL push-only)

        Args:
            zone: Trust zone ("bronze", "silver", "silverext"). Default: "silver"
            storage_account: DEPRECATED - use zone parameter instead
            use_default_credential: Use DefaultAzureCredential (True) or connection string (False)
            connection_string: Optional connection string (for airgapped accounts)

        Returns:
            BlobRepository singleton instance for that zone

        Example:
            # RECOMMENDED: Zone-based access (multi-account support)
            bronze_repo = RepositoryFactory.create_blob_repository("bronze")
            silver_repo = RepositoryFactory.create_blob_repository("silver")

            # ETL pattern: Bronze → Silver
            raw_data = bronze_repo.read_blob("bronze-rasters", "user_upload.tif")
            silver_repo.write_blob("silver-cogs", "processed.tif", cog_data)

            # Legacy usage still works (defaults to Silver)
            blob_repo = RepositoryFactory.create_blob_repository()
        """
        from .blob import BlobRepository

        logger.info(f"🏭 Creating Blob Storage repository for zone: {zone}")

        # Multi-account pattern (RECOMMENDED)
        if zone and zone in ["bronze", "silver", "silverext"]:
            logger.debug(f"  Using zone-based repository: {zone}")
            blob_repo = BlobRepository.for_zone(zone)

        # Legacy pattern (backward compatible)
        elif connection_string:
            logger.debug("  Using connection string authentication")
            blob_repo = BlobRepository.instance(connection_string=connection_string)
        else:
            logger.debug(f"  Using DefaultAzureCredential for account: {storage_account or 'from config'}")
            blob_repo = BlobRepository.instance(account_name=storage_account)

        logger.info("✅ Blob repository created successfully")
        return blob_repo
    
    @staticmethod
    def create_duckdb_repository(
        connection_type: str = "memory",
        database_path: Optional[str] = None,
        storage_account: Optional[str] = None
    ) -> 'DuckDBRepository':
        """
        Create DuckDB repository for analytical workloads.

        This is THE centralized creation point for DuckDB operations.
        DuckDB provides serverless queries over Azure Blob Storage,
        spatial analytics, and GeoParquet exports.

        Args:
            connection_type: "memory" (default) or "persistent"
            database_path: Path to database file (for persistent mode)
            storage_account: Azure storage account name (uses env if not provided)

        Returns:
            DuckDBRepository singleton instance

        Example:
            # In-memory analytics (default)
            duckdb_repo = RepositoryFactory.create_duckdb_repository()

            # Persistent database
            duckdb_repo = RepositoryFactory.create_duckdb_repository(
                connection_type="persistent",
                database_path="/data/analytics.duckdb"
            )

            # Query Parquet in blob storage (NO DOWNLOAD!)
            # Use config.storage.silver.get_container() for container name
            result = duckdb_repo.read_parquet_from_blob(
                config.storage.silver.misc,  # Use config for container name
                'exports/2025/*.parquet'
            )
        """
        from .duckdb import DuckDBRepository

        logger.info("🦆 Creating DuckDB repository")
        logger.debug(f"  Connection type: {connection_type}")
        logger.debug(f"  Database path: {database_path or 'N/A'}")
        logger.debug(f"  Storage account: {storage_account or 'from environment'}")

        duckdb_repo = DuckDBRepository.instance(
            connection_type=connection_type,
            database_path=database_path,
            storage_account_name=storage_account
        )

        logger.info("✅ DuckDB repository created successfully")
        return duckdb_repo

    @staticmethod
    def create_data_factory_repository() -> 'AzureDataFactoryRepository':
        """
        Create Azure Data Factory repository for pipeline orchestration.

        Use this to trigger ADF pipelines from CoreMachine jobs for
        database-to-database ETL operations with audit logging.

        Configuration (via environment variables):
        - ADF_SUBSCRIPTION_ID: Azure subscription ID (required)
        - ADF_RESOURCE_GROUP: Resource group (default: rmhazure_rg)
        - ADF_FACTORY_NAME: Data Factory instance name (required)

        Returns:
            AzureDataFactoryRepository singleton instance

        Raises:
            RuntimeError: If ADF SDK not installed or configuration missing

        Example:
            # Get repository
            adf_repo = RepositoryFactory.create_data_factory_repository()

            # Trigger pipeline
            result = adf_repo.trigger_pipeline(
                "CopyStagingToBusinessData",
                parameters={"table_name": "my_table", "job_id": "abc123"}
            )

            # Wait for completion
            final = adf_repo.wait_for_pipeline_completion(result['run_id'])
        """
        from .data_factory import AzureDataFactoryRepository

        logger.info("🏭 Creating Azure Data Factory repository")
        adf_repo = AzureDataFactoryRepository.instance()
        logger.info("✅ Azure Data Factory repository created successfully")

        return adf_repo

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