"""
Configuration module for Azure Functions geospatial ETL pipeline
Centralized environment variable management
"""
import os
from typing import Optional


class Config:
    """Configuration class for environment variables"""
    
    # Azure Storage Configuration
    STORAGE_ACCOUNT_NAME: Optional[str] = os.environ.get('STORAGE_ACCOUNT_NAME')
    AZURE_WEBJOBS_STORAGE: Optional[str] = os.environ.get('AzureWebJobsStorage')
    BRONZE_CONTAINER_NAME: str = os.environ.get('BRONZE_CONTAINER_NAME', 'bronze')
    #Silver container hosts COGs 
    SILVER_CONTAINER_NAME: str = os.environ.get('SILVER_CONTAINER_NAME', 'silver')
    #Gold container has GeoParquet mirroring selections from Silver Database
    GOLD_CONTAINER_NAME: str = os.environ.get('GOLD_CONTAINER_NAME', 'gold')
    
    
    # PostGIS Database Configuration
    POSTGIS_HOST: str = os.environ.get('POSTGIS_HOST', 'localhost')
    POSTGIS_PORT: int = int(os.environ.get('POSTGIS_PORT', '5432'))
    POSTGIS_USER: str = os.environ.get('POSTGIS_USER', 'postgres')
    POSTGIS_PASSWORD: Optional[str] = os.environ.get('POSTGIS_PASSWORD')
    # This is the database half of silver storage
    POSTGIS_DATABASE: str = os.environ.get('POSTGIS_DATABASE', 'geodata')
    
    
    # Application Configuration
    FUNCTION_TIMEOUT: int = int(os.environ.get('FUNCTION_TIMEOUT', '300'))  # 5 minutes default
    MAX_RETRY_ATTEMPTS: int = int(os.environ.get('MAX_RETRY_ATTEMPTS', '3'))
    LOG_LEVEL: str = os.environ.get('LOG_LEVEL', 'INFO')
    
    @classmethod
    def validate_storage_config(cls) -> None:
        """Validate that required storage configuration is present"""
        if not cls.STORAGE_ACCOUNT_NAME and not cls.AZURE_WEBJOBS_STORAGE:
            raise ValueError(
                "Either STORAGE_ACCOUNT_NAME or AzureWebJobsStorage environment variable must be set"
            )
    
    @classmethod
    def validate_postgis_config(cls) -> None:
        """Validate that required PostGIS configuration is present"""
        if not cls.POSTGIS_PASSWORD:
            raise ValueError("POSTGIS_PASSWORD environment variable must be set")
        
        if not cls.POSTGIS_HOST:
            raise ValueError("POSTGIS_HOST environment variable must be set")
    
    @classmethod
    def get_postgis_connection_string(cls) -> str:
        """Get PostGIS connection string"""
        cls.validate_postgis_config()
        
        return (
            f"postgresql://{cls.POSTGIS_USER}:{cls.POSTGIS_PASSWORD}"
            f"@{cls.POSTGIS_HOST}:{cls.POSTGIS_PORT}/{cls.POSTGIS_DATABASE}"
        )
    
    @classmethod
    def get_storage_account_url(cls, service: str = 'blob') -> str:
        """Get storage account URL for specified service"""
        cls.validate_storage_config()
        
        if not cls.STORAGE_ACCOUNT_NAME:
            raise ValueError("STORAGE_ACCOUNT_NAME not configured for managed identity")
        
        return f"https://{cls.STORAGE_ACCOUNT_NAME}.{service}.core.windows.net"
    
    @classmethod
    def get_bronze_container_url(cls) -> str:
        """Get full URL to bronze container"""
        blob_url = cls.get_storage_account_url('blob')
        return f"{blob_url}/{cls.BRONZE_CONTAINER_NAME}"
    
    @classmethod
    def debug_config(cls) -> dict:
        """Get configuration summary for debugging (masks sensitive values)"""
        return {
            'storage_account_name': cls.STORAGE_ACCOUNT_NAME,
            'azure_webjobs_storage_configured': bool(cls.AZURE_WEBJOBS_STORAGE),
            'bronze_container_name': cls.BRONZE_CONTAINER_NAME,
            'postgis_host': cls.POSTGIS_HOST,
            'postgis_port': cls.POSTGIS_PORT,
            'postgis_user': cls.POSTGIS_USER,
            'postgis_password_configured': bool(cls.POSTGIS_PASSWORD),
            'postgis_database': cls.POSTGIS_DATABASE,
            'function_timeout': cls.FUNCTION_TIMEOUT,
            'max_retry_attempts': cls.MAX_RETRY_ATTEMPTS,
            'log_level': cls.LOG_LEVEL
        }