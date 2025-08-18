"""
Configuration module for Azure Functions geospatial ETL pipeline
Centralized environment variable management and constants
"""
import os
from typing import Optional


class EnvVarNames:
    """Environment variable name constants - centralized for easy changes"""
    
    # Azure Storage Environment Variables
    STORAGE_ACCOUNT_NAME = 'STORAGE_ACCOUNT_NAME'
    AZURE_WEBJOBS_STORAGE = 'AzureWebJobsStorage'
    BRONZE_CONTAINER_NAME = 'BRONZE_CONTAINER_NAME'
    SILVER_CONTAINER_NAME = 'SILVER_CONTAINER_NAME'
    GOLD_CONTAINER_NAME = 'GOLD_CONTAINER_NAME'
    
    # PostGIS Database Environment Variables
    POSTGIS_HOST = 'POSTGIS_HOST'
    
    POSTGIS_PORT = 'POSTGIS_PORT'
    POSTGIS_USER = 'POSTGIS_USER'
    POSTGIS_PASSWORD = 'POSTGIS_PASSWORD'
    POSTGIS_DATABASE = 'POSTGIS_DATABASE'
    POSTGIS_SCHEMA = 'POSTGIS_SCHEMA'
    
    # Application Environment Variables
    FUNCTION_TIMEOUT = 'FUNCTION_TIMEOUT'
    MAX_RETRY_ATTEMPTS = 'MAX_RETRY_ATTEMPTS'
    LOG_LEVEL = 'LOG_LEVEL'


class Config:
    """Configuration class for environment variables"""
    
    # Azure Storage Configuration
    # Extract storage account name from AzureWebJobsStorage__blobServiceUri or use explicit setting
    _storage_uri = os.environ.get('AzureWebJobsStorage__blobServiceUri', '')
    if _storage_uri and _storage_uri.startswith('https://'):
        # Extract account name from URI like https://rmhazuregeo.blob.core.windows.net
        STORAGE_ACCOUNT_NAME = _storage_uri.split('//')[1].split('.')[0] if '//' in _storage_uri else None
    else:
        # Fallback to explicit STORAGE_ACCOUNT_NAME environment variable
        STORAGE_ACCOUNT_NAME: Optional[str] = os.environ.get(EnvVarNames.STORAGE_ACCOUNT_NAME)
    
    AZURE_WEBJOBS_STORAGE: Optional[str] = os.environ.get(EnvVarNames.AZURE_WEBJOBS_STORAGE)
    BRONZE_CONTAINER_NAME: Optional[str] = os.environ.get(EnvVarNames.BRONZE_CONTAINER_NAME)
    #Silver container hosts COGs 
    SILVER_CONTAINER_NAME: Optional[str] = os.environ.get(EnvVarNames.SILVER_CONTAINER_NAME)
    #Gold container has GeoParquet mirroring selections from Silver Database
    GOLD_CONTAINER_NAME: Optional[str] = os.environ.get(EnvVarNames.GOLD_CONTAINER_NAME)
    
    
    # PostGIS Database Configuration
    POSTGIS_HOST: Optional[str] = os.environ.get(EnvVarNames.POSTGIS_HOST)
    POSTGIS_PORT: Optional[int] = int(os.environ.get(EnvVarNames.POSTGIS_PORT)) if os.environ.get(EnvVarNames.POSTGIS_PORT) else None
    POSTGIS_USER: Optional[str] = os.environ.get(EnvVarNames.POSTGIS_USER)
    POSTGIS_PASSWORD: Optional[str] = os.environ.get(EnvVarNames.POSTGIS_PASSWORD)
    # This is the database half of silver storage
    POSTGIS_DATABASE: Optional[str] = os.environ.get(EnvVarNames.POSTGIS_DATABASE)
    POSTGIS_SCHEMA: Optional[str] = os.environ.get(EnvVarNames.POSTGIS_SCHEMA)
    
    
    # Application Configuration (these can have sensible defaults)
    FUNCTION_TIMEOUT: int = int(os.environ.get(EnvVarNames.FUNCTION_TIMEOUT, '300'))  # 5 minutes default
    MAX_RETRY_ATTEMPTS: int = int(os.environ.get(EnvVarNames.MAX_RETRY_ATTEMPTS, '3'))
    LOG_LEVEL: str = os.environ.get(EnvVarNames.LOG_LEVEL, 'INFO')
    
    @classmethod
    def validate_storage_config(cls) -> None:
        """Validate that required storage configuration is present"""
        if not cls.STORAGE_ACCOUNT_NAME:
            raise ValueError(
                f"{EnvVarNames.STORAGE_ACCOUNT_NAME} environment variable must be set for managed identity"
            )
    
    @classmethod
    def validate_container_config(cls) -> None:
        """Validate that required container configuration is present"""
        if not cls.BRONZE_CONTAINER_NAME:
            raise ValueError(f"{EnvVarNames.BRONZE_CONTAINER_NAME} environment variable must be set")
        if not cls.SILVER_CONTAINER_NAME:
            raise ValueError(f"{EnvVarNames.SILVER_CONTAINER_NAME} environment variable must be set")
        if not cls.GOLD_CONTAINER_NAME:
            raise ValueError(f"{EnvVarNames.GOLD_CONTAINER_NAME} environment variable must be set")
    
    @classmethod
    def validate_postgis_config(cls) -> None:
        """Validate that required PostGIS configuration is present"""
        if not cls.POSTGIS_HOST:
            raise ValueError(f"{EnvVarNames.POSTGIS_HOST} environment variable must be set")
        if not cls.POSTGIS_PORT:
            raise ValueError(f"{EnvVarNames.POSTGIS_PORT} environment variable must be set")
        if not cls.POSTGIS_USER:
            raise ValueError(f"{EnvVarNames.POSTGIS_USER} environment variable must be set")
        # POSTGIS_PASSWORD is optional when using managed identity
        if not cls.POSTGIS_DATABASE:
            raise ValueError(f"{EnvVarNames.POSTGIS_DATABASE} environment variable must be set")
        if not cls.POSTGIS_SCHEMA:
            raise ValueError(f"{EnvVarNames.POSTGIS_SCHEMA} environment variable must be set")
    
    @classmethod
    def get_postgis_connection_string(cls, include_schema: bool = False) -> str:
        """Get PostGIS connection string"""
        cls.validate_postgis_config()
        
        # Build connection string with or without password (for managed identity)
        if cls.POSTGIS_PASSWORD:
            # Traditional authentication with password
            connection_string = (
                f"postgresql://{cls.POSTGIS_USER}:{cls.POSTGIS_PASSWORD}"
                f"@{cls.POSTGIS_HOST}:{cls.POSTGIS_PORT}/{cls.POSTGIS_DATABASE}"
            )
        else:
            # Managed identity authentication (no password)
            connection_string = (
                f"postgresql://{cls.POSTGIS_USER}"
                f"@{cls.POSTGIS_HOST}:{cls.POSTGIS_PORT}/{cls.POSTGIS_DATABASE}"
            )
        
        if include_schema:
            connection_string += f"?options=-csearch_path={cls.POSTGIS_SCHEMA}"
        
        return connection_string
    
    @classmethod
    def get_storage_account_url(cls, service: str = 'blob') -> str:
        """Get storage account URL for specified service"""
        cls.validate_storage_config()
        
        if not cls.STORAGE_ACCOUNT_NAME:
            raise ValueError(f"{EnvVarNames.STORAGE_ACCOUNT_NAME} not configured for managed identity")
        
        return f"https://{cls.STORAGE_ACCOUNT_NAME}.{service}.core.windows.net"
    
    @classmethod
    def get_bronze_container_url(cls) -> str:
        """Get full URL to bronze container"""
        cls.validate_container_config()
        blob_url = cls.get_storage_account_url('blob')
        return f"{blob_url}/{cls.BRONZE_CONTAINER_NAME}"
    
    @classmethod
    def debug_config(cls) -> dict:
        """Get configuration summary for debugging (masks sensitive values)"""
        return {
            'storage_account_name': cls.STORAGE_ACCOUNT_NAME,
            'azure_webjobs_storage_configured': bool(cls.AZURE_WEBJOBS_STORAGE),
            'bronze_container_name': cls.BRONZE_CONTAINER_NAME,
            'silver_container_name': cls.SILVER_CONTAINER_NAME,
            'gold_container_name': cls.GOLD_CONTAINER_NAME,
            'postgis_host': cls.POSTGIS_HOST,
            'postgis_port': cls.POSTGIS_PORT,
            'postgis_user': cls.POSTGIS_USER,
            'postgis_password_configured': bool(cls.POSTGIS_PASSWORD),
            'postgis_database': cls.POSTGIS_DATABASE,
            'postgis_schema': cls.POSTGIS_SCHEMA,
            'function_timeout': cls.FUNCTION_TIMEOUT,
            'max_retry_attempts': cls.MAX_RETRY_ATTEMPTS,
            'log_level': cls.LOG_LEVEL
        }


# API Parameter Names - Change these to update across entire application
class APIParams:
    """HTTP API parameter names"""
    DATASET_ID = "dataset_id"
    RESOURCE_ID = "resource_id"
    VERSION_ID = "version_id"
    OPERATION_TYPE = "operation_type"
    SYSTEM = "system"
    
    # Job tracking parameters
    JOB_ID = "job_id"
    STATUS = "status"
    MESSAGE = "message"
    IS_DUPLICATE = "is_duplicate"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    ERROR_MESSAGE = "error_message"
    RESULT_DATA = "result_data"


# Operation Types
class Operations:
    """Supported operation types"""
    HELLO_WORLD = "hello_world"
    LIST_CONTAINER = "list_container"
    COG_CONVERSION = "cog_conversion"
    VECTOR_UPLOAD = "vector_upload"
    STAC_GENERATION = "stac_generation"


# Job Status Values
class JobStatuses:
    """Job status constants"""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Default Values
class Defaults:
    """Default parameter values"""
    SYSTEM_FLAG = False
    NO_FILTER = "none"
    DEFAULT_VERSION = "v1.0.0"
    

# Validation Constants
class Validation:
    """Validation rules and patterns"""
    INVALID_DATASET_CHARS = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    INVALID_RESOURCE_CHARS = [':', '*', '?', '"', '<', '>', '|']
    

# Azure Storage Configuration
class AzureStorage:
    """Azure Storage service names and configuration constants"""
    JOB_PROCESSING_QUEUE = "geospatial-jobs"
    JOB_TRACKING_TABLE = "jobs"
    FUNCTIONS_KEY_HEADER = "x-functions-key"
    STORAGE_CONNECTION = "AzureWebJobsStorage"
    # For managed identity connections, Azure Functions expects: {ConnectionName}__serviceUri
    MANAGED_IDENTITY_CONNECTION = "Storage"