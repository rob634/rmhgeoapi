# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Central configuration management with Pydantic v2 validation
# SOURCE: Environment variables with fallback defaults and computed properties
# SCOPE: Global application configuration for all services and components
# VALIDATION: Pydantic v2 runtime validation with Azure naming convention checks
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
        description="PostgreSQL schema name for application tables (jobs, tasks, etc.)",
        examples=["rmhgeoapi", "dev_rmhgeoapi", "prod_rmhgeoapi"]
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
    # Security Configuration - Azure Key Vault
    # ========================================================================
    
    key_vault_name: str = Field(
        default="rmhkeyvault",
        description="Azure Key Vault name for secure credential storage",
        examples=["rmhkeyvault", "rmhazurevault"]
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
        if self.postgis_password:
            return (
                f"postgresql://{self.postgis_user}:{self.postgis_password}"
                f"@{self.postgis_host}:{self.postgis_port}/{self.postgis_database}"
            )
        else:
            # Managed identity or no password authentication
            return (
                f"postgresql://{self.postgis_user}"
                f"@{self.postgis_host}:{self.postgis_port}/{self.postgis_database}"
            )
    
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
            app_schema=os.environ.get('APP_SCHEMA', 'rmhgeoapi'),
            
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
            'key_vault_name': config.key_vault_name,
            'key_vault_database_secret': config.key_vault_database_secret,
            'job_queue': config.job_processing_queue,
            'task_queue': config.task_processing_queue,
            'function_timeout_minutes': config.function_timeout_minutes,
            'log_level': config.log_level,
        }
    except Exception as e:
        return {'error': f'Configuration validation failed: {e}'}


if __name__ == "__main__":
    # Quick test/debug when run directly
    import json
    print("Configuration Debug:")
    print(json.dumps(debug_config(), indent=2))