# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Epoch 3 COMPLETELY DEPRECATED - Service Bus only application
# NOTE: This is a SERVICE BUS ONLY application - Storage Queues are NOT supported
# PURPOSE: Central configuration management with Pydantic v2 validation for Azure Geospatial ETL Pipeline
# EXPORTS: AppConfig, get_config(), QueueNames, debug_config()
# INTERFACES: Pydantic BaseModel for configuration management
# PYDANTIC_MODELS: AppConfig (main configuration model with all settings)
# DEPENDENCIES: pydantic, os, typing, json
# SOURCE: Environment variables with fallback defaults, Azure Key Vault for secrets
# SCOPE: Global application configuration for all services and components
# VALIDATION: Pydantic v2 runtime validation with Azure naming convention checks and custom validators
# PATTERNS: Settings pattern, Singleton (via cached get_config), Factory method pattern
# ENTRY_POINTS: from config import get_config; config = get_config(); url = config.blob_service_url
# INDEX: AppConfig:55, PostgreSQL config:94, Queue config:171, get_config:324, QueueNames:355, debug_config:365
# ============================================================================

"""
Strongly Typed Configuration Management - Azure Geospatial ETL Pipeline

Centralized configuration management using Pydantic v2 for runtime validation,
type safety, and comprehensive documentation of all environment variables.
Provides single source of truth for application configuration across all components.

Key Features:
- Pydantic v2 schema validation with runtime type checking
- Environment variable documentation with examples and descriptions
- Computed properties for Azure service URLs and connection strings
- Validation for Azure naming conventions and constraints
- Factory methods for different initialization patterns
- Development helpers with sanitized debug output

Configuration Categories:
- Azure Storage: Storage account, container names, service URLs
- PostgreSQL/PostGIS: Database connection and schema configuration
- Security: Azure Key Vault integration for credential management
- Queues: Processing queue names and configuration
- Application: Timeouts, retry policies, logging levels

Integration Points:
- Used by all Azure Functions triggers for consistent configuration
- Repository layer uses database connection settings
- Storage adapters use Azure Storage configuration
- Health checks validate all configuration components
- Vault repository retrieves secure credentials

Usage Examples:
    # Standard application usage
    config = get_config()
    blob_url = config.blob_service_url
    
    # Development debugging (safe - passwords masked)
    debug_info = debug_config()
    print(json.dumps(debug_info, indent=2))

Author: Azure Geospatial ETL Team
"""
import os
from typing import Optional
from pydantic import BaseModel, Field, field_validator, ValidationError


class AppConfig(BaseModel):
    """
    Strongly typed application configuration using Pydantic v2.
    
    All environment variables are documented, validated, and typed.
    Provides single source of truth for configuration management.
    """
    
    # ========================================================================
    # Azure Storage Configuration
    # ========================================================================
    
    storage_account_name: str = Field(
        ...,  # Required field
        description="Azure Storage Account name for managed identity authentication",
        examples=["rmhazuregeo"]
    )
    
    bronze_container_name: str = Field(
        ...,
        description="Bronze tier container name for raw geospatial data",
        examples=["rmhazuregeobronze"]
    )
    
    silver_container_name: str = Field(
        ...,
        description="Silver tier container name for processed COGs and structured data",
        examples=["rmhazuregeosilver"]
    )
    
    gold_container_name: str = Field(
        ...,
        description="Gold tier container name for GeoParquet exports and analytics",
        examples=["rmhazuregeogold"]
    )

    # ========================================================================
    # Vector ETL Configuration
    # ========================================================================

    vector_pickle_container: str = Field(
        default="rmhazuregeotemp",
        description="Container for vector ETL intermediate pickle files",
        examples=["rmhazuregeotemp", "silver"]
    )

    vector_pickle_prefix: str = Field(
        default="temp/vector_etl",
        description="Blob path prefix for vector ETL pickle files",
        examples=["temp/vector_etl", "intermediate/vector"]
    )

    # ========================================================================
    # Raster Pipeline Configuration
    # ========================================================================

    raster_intermediate_prefix: str = Field(
        default="temp/raster_etl",
        description="Blob path prefix for raster ETL intermediate files (large file tiles)",
        examples=["temp/raster_etl", "intermediate/raster"]
    )

    raster_size_threshold_mb: int = Field(
        default=1000,  # 1 GB
        description="File size threshold (MB) for pipeline selection (small vs large file)",
    )

    raster_cog_compression: str = Field(
        default="deflate",
        description="Default compression algorithm for COG creation",
        examples=["deflate", "lzw", "zstd", "jpeg", "webp", "lerc_deflate"]
    )

    raster_cog_jpeg_quality: int = Field(
        default=85,
        description="JPEG quality for lossy compression (1-100, only applies to jpeg/webp)",
    )

    raster_cog_tile_size: int = Field(
        default=512,
        description="Internal tile size for COG (pixels)",
    )

    raster_overview_resampling: str = Field(
        default="cubic",
        description="Resampling method for COG overview generation",
        examples=["cubic", "bilinear", "average", "mode", "nearest"]
    )

    raster_reproject_resampling: str = Field(
        default="cubic",
        description="Resampling method for reprojection",
        examples=["cubic", "bilinear", "lanczos", "nearest"]
    )

    raster_strict_validation: bool = Field(
        default=False,
        description="Fail on validation warnings (inefficient bit-depth, etc)",
    )

    raster_cog_in_memory: bool = Field(
        default=True,
        description="Process COG creation in-memory (True) vs disk-based (False). "
                    "In-memory is faster for small files (<1GB) but uses more RAM. "
                    "Disk-based uses local SSD temp storage, better for large files.",
    )

    # ========================================================================
    # PostgreSQL/PostGIS Configuration
    # ========================================================================
    
    postgis_host: str = Field(
        ...,
        description="PostgreSQL server hostname for STAC catalog and metadata",
        examples=["rmhpgflex.postgres.database.azure.com"]
    )
    
    postgis_port: int = Field(
        default=5432,
        description="PostgreSQL server port number"
    )
    
    postgis_user: str = Field(
        ...,
        description="PostgreSQL username for database connections"
    )
    
    postgis_password: Optional[str] = Field(
        default=None,
        description="""PostgreSQL password from POSTGIS_PASSWORD environment variable.
        
        IMPORTANT: Two access patterns exist for this password:
        1. config.postgis_password (used by health checks) - via this config system
        2. os.environ.get('POSTGIS_PASSWORD') (used by PostgreSQL adapter) - direct access
        
        Both patterns access the same POSTGIS_PASSWORD environment variable.
        The direct access pattern was implemented during Key Vault → env var migration.
        
        For new code: Use config.postgis_password for consistency with other config values.
        """
    )
    
    postgis_database: str = Field(
        ...,
        description="PostgreSQL database name containing STAC catalog",
        examples=["geopgflex"]
    )
    
    postgis_schema: str = Field(
        default="geo",
        description="PostgreSQL schema name for STAC collections and items"
    )
    
    app_schema: str = Field(
        default="app",
        description="PostgreSQL schema name for application tables (jobs, tasks, etc.)"
    )
    
    # ========================================================================
    # Queue Processing Configuration
    # ========================================================================
    
    job_processing_queue: str = Field(
        default="geospatial-jobs",
        description="Azure Storage Queue for job orchestration messages"
    )
    
    task_processing_queue: str = Field(
        default="geospatial-tasks", 
        description="Azure Storage Queue for individual task processing"
    )
    
    # ========================================================================
    # Service Bus Configuration (for parallel processing pipeline)
    # ========================================================================

    service_bus_connection_string: Optional[str] = Field(
        default=None,
        description="Service Bus connection string for local development"
    )

    service_bus_namespace: Optional[str] = Field(
        default=None,
        description="Service Bus namespace for managed identity auth"
    )

    service_bus_jobs_queue: str = Field(
        default="geospatial-jobs",
        description="Service Bus queue name for job messages"
    )

    service_bus_tasks_queue: str = Field(
        default="geospatial-tasks",
        description="Service Bus queue name for task messages"
    )

    service_bus_max_batch_size: int = Field(
        default=100,
        description="Maximum batch size for Service Bus messages"
    )

    service_bus_retry_count: int = Field(
        default=3,
        description="Number of retry attempts for Service Bus operations"
    )

    # ========================================================================
    # Task Retry Configuration - Exponential Backoff
    # ========================================================================

    task_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed tasks (0 = no retries)"
    )

    task_retry_base_delay: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Base delay in seconds for exponential backoff (first retry)"
    )

    task_retry_max_delay: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Maximum delay in seconds between retries (5 minutes default)"
    )

    # ========================================================================
    # Security Configuration - Azure Key Vault
    # ========================================================================
    
    key_vault_name: str = Field(
        default="rmhazurevault",
        description="Azure Key Vault name for secure credential storage"
    )
    
    key_vault_database_secret: str = Field(
        default="postgis-password",
        description="Name of the secret in Key Vault containing the PostgreSQL password",
        examples=["postgis-password", "database-password"]
    )
    
    # ========================================================================
    # Application Configuration
    # ========================================================================
    
    function_timeout_minutes: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Azure Function timeout in minutes (1-10 range)"
    )
    
    max_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for failed operations"
    )
    
    log_level: str = Field(
        default="INFO",
        description="Logging level for application diagnostics"
    )
    
    enable_database_health_check: bool = Field(
        default=True,
        description="Enable PostgreSQL connectivity checks in health endpoint"
    )
    
    # ========================================================================
    # Computed Properties
    # ========================================================================
    
    @property
    def blob_service_url(self) -> str:
        """Azure Blob Storage service URL for managed identity"""
        return f"https://{self.storage_account_name}.blob.core.windows.net"
    
    @property
    def queue_service_url(self) -> str:
        """Azure Queue Storage service URL for managed identity"""
        return f"https://{self.storage_account_name}.queue.core.windows.net"
    
    @property
    def table_service_url(self) -> str:
        """Azure Table Storage service URL for managed identity"""
        return f"https://{self.storage_account_name}.table.core.windows.net"
    
    @property
    def postgis_connection_string(self) -> str:
        """PostgreSQL connection string with or without password"""
        import logging
        from urllib.parse import quote_plus
        logger = logging.getLogger(__name__)
        
        # Log the components being used
        logger.debug(f"🔍 Building PostgreSQL connection string:")
        logger.debug(f"  Host: {self.postgis_host}")
        logger.debug(f"  Port: {self.postgis_port}")
        logger.debug(f"  User: {self.postgis_user}")
        logger.debug(f"  Database: {self.postgis_database}")
        logger.debug(f"  Password configured: {bool(self.postgis_password)}")
        
        if self.postgis_password:
            # URL-encode the password to handle special characters like @
            encoded_password = quote_plus(self.postgis_password)
            conn_str = (
                f"postgresql://{self.postgis_user}:{encoded_password}"
                f"@{self.postgis_host}:{self.postgis_port}/{self.postgis_database}"
            )
            # Log connection string with password masked
            logger.debug(f"  Connection string: postgresql://{self.postgis_user}:****@{self.postgis_host}:{self.postgis_port}/{self.postgis_database}")
            logger.debug(f"  Password contains special characters: {'@' in self.postgis_password}")
        else:
            # Managed identity or no password authentication
            conn_str = (
                f"postgresql://{self.postgis_user}"
                f"@{self.postgis_host}:{self.postgis_port}/{self.postgis_database}"
            )
            logger.debug(f"  Connection string: {conn_str}")
        
        return conn_str
    
    # ========================================================================
    # Validation
    # ========================================================================
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the standard Python logging levels"""
        valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of: {', '.join(valid_levels)}")
        return v.upper()
    
    @field_validator('storage_account_name')
    @classmethod
    def validate_storage_account_name(cls, v: str) -> str:
        """Validate Azure Storage account name format"""
        if not v.islower():
            raise ValueError("storage_account_name must be lowercase")
        if not v.replace('-', '').isalnum():
            raise ValueError("storage_account_name must contain only lowercase letters, numbers, and hyphens")
        if len(v) < 3 or len(v) > 24:
            raise ValueError("storage_account_name must be 3-24 characters long")
        return v
    
    # ========================================================================
    # Factory Methods
    # ========================================================================
    
    @classmethod
    def from_environment(cls) -> 'AppConfig':
        """
        Create configuration from environment variables.
        
        Raises:
            ValidationError: If required environment variables are missing or invalid
        """
        return cls(
            # Azure Storage
            storage_account_name=os.environ['STORAGE_ACCOUNT_NAME'],
            bronze_container_name=os.environ['BRONZE_CONTAINER_NAME'],
            silver_container_name=os.environ['SILVER_CONTAINER_NAME'],
            gold_container_name=os.environ['GOLD_CONTAINER_NAME'],
            
            # PostgreSQL
            postgis_host=os.environ['POSTGIS_HOST'],
            postgis_port=int(os.environ.get('POSTGIS_PORT', '5432')),
            postgis_user=os.environ['POSTGIS_USER'],
            postgis_password=os.environ.get('POSTGIS_PASSWORD'),
            postgis_database=os.environ['POSTGIS_DATABASE'],
            postgis_schema=os.environ.get('POSTGIS_SCHEMA', 'geo'),
            app_schema=os.environ.get('APP_SCHEMA', 'app'),

            # Vector ETL
            vector_pickle_container=os.environ.get('VECTOR_PICKLE_CONTAINER', 'rmhazuregeotemp'),
            vector_pickle_prefix=os.environ.get('VECTOR_PICKLE_PREFIX', 'temp/vector_etl'),
            
            # Security
            key_vault_name=os.environ.get('KEY_VAULT', 'rmhkeyvault'),
            key_vault_database_secret=os.environ.get('KEY_VAULT_DATABASE_SECRET', 'postgis-password'),
            
            # Application
            function_timeout_minutes=int(os.environ.get('FUNCTION_TIMEOUT_MINUTES', '5')),
            max_retry_attempts=int(os.environ.get('MAX_RETRY_ATTEMPTS', '3')),
            log_level=os.environ.get('LOG_LEVEL', 'INFO'),
            enable_database_health_check=os.environ.get('ENABLE_DATABASE_HEALTH_CHECK', 'true').lower() == 'true',
            
            # Queues (usually defaults are fine)
            job_processing_queue=os.environ.get('JOB_PROCESSING_QUEUE', 'geospatial-jobs'),
            task_processing_queue=os.environ.get('TASK_PROCESSING_QUEUE', 'geospatial-tasks'),

            # Service Bus (optional)
            service_bus_connection_string=os.environ.get('SERVICE_BUS_CONNECTION_STRING'),
            service_bus_namespace=os.environ.get('SERVICE_BUS_NAMESPACE') or os.environ.get('ServiceBusConnection__fullyQualifiedNamespace'),
            service_bus_jobs_queue=os.environ.get('SERVICE_BUS_JOBS_QUEUE', 'geospatial-jobs'),
            service_bus_tasks_queue=os.environ.get('SERVICE_BUS_TASKS_QUEUE', 'geospatial-tasks'),
            service_bus_max_batch_size=int(os.environ.get('SERVICE_BUS_MAX_BATCH_SIZE', '100')),
            service_bus_retry_count=int(os.environ.get('SERVICE_BUS_RETRY_COUNT', '3')),

            # Task retry configuration
            task_max_retries=int(os.environ.get('TASK_MAX_RETRIES', '3')),
            task_retry_base_delay=int(os.environ.get('TASK_RETRY_BASE_DELAY', '5')),
            task_retry_max_delay=int(os.environ.get('TASK_RETRY_MAX_DELAY', '300')),
        )
    
    def validate_runtime_dependencies(self) -> None:
        """
        Validate that runtime dependencies are accessible.
        Call this during application startup to fail fast.
        """
        # Could add actual connectivity tests here
        # For now, just validate required fields exist
        required_fields = [
            'storage_account_name', 'bronze_container_name', 
            'silver_container_name', 'gold_container_name',
            'postgis_host', 'postgis_user', 'postgis_database'
        ]
        
        for field in required_fields:
            value = getattr(self, field)
            if not value:
                raise ValueError(f"Configuration field '{field}' is required but empty")


# ========================================================================
# Global Configuration Instance
# ========================================================================

def get_config() -> AppConfig:
    """
    Get the global application configuration.
    
    Creates and validates configuration from environment variables on first call.
    Subsequent calls return the cached instance.
    
    Raises:
        ValidationError: If configuration is invalid
        KeyError: If required environment variables are missing
    """
    global _config_instance
    if _config_instance is None:
        try:
            _config_instance = AppConfig.from_environment()
            _config_instance.validate_runtime_dependencies()
        except KeyError as e:
            raise ValueError(f"Missing required environment variable: {e}")
        except ValidationError as e:
            raise ValueError(f"Configuration validation failed: {e}")
    return _config_instance


# Global instance (lazy loaded)
_config_instance: Optional[AppConfig] = None


# ========================================================================
# Legacy Constants (for backwards compatibility during migration)
# ========================================================================

class QueueNames:
    """Queue name constants for easy access"""
    JOBS = "geospatial-jobs"
    TASKS = "geospatial-tasks"


# ========================================================================
# Development Helpers
# ========================================================================

def debug_config() -> dict:
    """
    Get sanitized configuration for debugging (masks sensitive values).
    
    Returns:
        Dictionary with configuration values, passwords masked
    """
    try:
        config = get_config()
        return {
            'storage_account_name': config.storage_account_name,
            'bronze_container': config.bronze_container_name,
            'silver_container': config.silver_container_name,
            'gold_container': config.gold_container_name,
            'postgis_host': config.postgis_host,
            'postgis_port': config.postgis_port,
            'postgis_user': config.postgis_user,
            'postgis_password_set': bool(config.postgis_password),
            'postgis_database': config.postgis_database,
            'postgis_schema': config.postgis_schema,
            'app_schema': config.app_schema,
            'vector_pickle_container': config.vector_pickle_container,
            'vector_pickle_prefix': config.vector_pickle_prefix,
            'key_vault_name': config.key_vault_name,
            'key_vault_database_secret': config.key_vault_database_secret,
            'job_queue': config.job_processing_queue,
            'task_queue': config.task_processing_queue,
            'function_timeout_minutes': config.function_timeout_minutes,
            'log_level': config.log_level,
        }
    except Exception as e:
        return {'error': f'Configuration validation failed: {e}'}

