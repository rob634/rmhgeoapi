# ============================================================================
# CLAUDE CONTEXT - APPLICATION CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New module - Phase 1 of config.py refactoring (20 NOV 2025)
# PURPOSE: Main application configuration - composes domain-specific configs
# LAST_REVIEWED: 20 NOV 2025
# EXPORTS: AppConfig
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: AppConfig
# DEPENDENCIES: pydantic, os, typing, domain config modules
# SOURCE: Environment variables + composed domain configs
# SCOPE: Application-wide configuration
# VALIDATION: Pydantic v2 validation
# PATTERNS: Composition over inheritance
# ENTRY_POINTS: from config import AppConfig, get_config
# INDEX: AppConfig:50
# ============================================================================

"""
Main Application Configuration - Composition Pattern

Composes domain-specific configuration modules:
- StorageConfig (COG tiers, multi-account storage)
- DatabaseConfig (PostgreSQL/PostGIS)
- RasterConfig (Raster pipeline)
- VectorConfig (Vector pipeline)
- QueueConfig (Service Bus queues)

This module was created as part of the config.py god object refactoring (20 NOV 2025).
It replaces the monolithic AppConfig class (1,090 lines, 63+ fields) with a
composition-based approach (150 lines, 5 domain configs).

Pattern:
    OLD: AppConfig with 63+ fields (god object)
    NEW: AppConfig composes 5 domain configs (composition)

Benefits:
    - Clear separation of concerns
    - Easier testing (mock only what you need)
    - Reduced merge conflicts
    - Better maintainability
"""

import os
from typing import Optional
from pydantic import BaseModel, Field

from .storage_config import StorageConfig
from .database_config import DatabaseConfig
from .raster_config import RasterConfig
from .vector_config import VectorConfig
from .queue_config import QueueConfig


# ============================================================================
# APPLICATION CONFIGURATION
# ============================================================================

class AppConfig(BaseModel):
    """
    Application configuration - composition of domain configs.

    NEW PATTERN: Instead of 63+ fields in one class, compose smaller configs.
    Each domain config manages its own validation and defaults.
    """

    # ========================================================================
    # Core Application Settings
    # ========================================================================

    debug_mode: bool = Field(
        default=False,
        description="Enable debug mode for verbose diagnostics. "
                    "WARNING: Increases logging overhead and log volume. "
                    "Features enabled: memory tracking, detailed timing, payload logging. "
                    "Set DEBUG_MODE=true in environment to enable.",
        examples=[True, False]
    )

    environment: str = Field(
        default="dev",
        description="Environment name (dev, qa, prod)",
        examples=["dev", "qa", "prod"]
    )

    # ========================================================================
    # Legacy Storage Settings (DEPRECATED - Use storage.* instead)
    # ========================================================================

    storage_account_name: str = Field(
        default="rmhazuregeo",
        description="DEPRECATED: Use storage.bronze.account_name instead. Azure Storage Account name for managed identity authentication",
        examples=["rmhazuregeo"],
        deprecated="Use storage.bronze.account_name, storage.silver.account_name, etc."
    )

    bronze_container_name: str = Field(
        default="rmhazuregeobronze",
        description="DEPRECATED: Use storage.bronze.get_container('rasters') instead",
        deprecated="Use storage.bronze.get_container() instead"
    )

    silver_container_name: str = Field(
        default="rmhazuregeosilver",
        description="DEPRECATED: Use storage.silver.get_container('cogs') instead",
        deprecated="Use storage.silver.get_container() instead"
    )

    gold_container_name: str = Field(
        default="rmhazuregeogold",
        description="DEPRECATED: Use storage.gold.get_container('vectors') instead",
        deprecated="Use storage.gold.get_container() instead"
    )

    # ========================================================================
    # Timeouts and Retries
    # ========================================================================

    function_timeout_minutes: int = Field(
        default=30,
        description="Function timeout in minutes (must match host.json functionTimeout)"
    )

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
        ge=10,
        le=3600,
        description="Maximum delay in seconds between retries (caps exponential growth)"
    )

    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for failed operations (general)"
    )

    # ========================================================================
    # Logging Configuration
    # ========================================================================

    log_level: str = Field(
        default="INFO",
        description="Logging level for application diagnostics",
        examples=["DEBUG", "INFO", "WARNING", "ERROR"]
    )

    # ========================================================================
    # Health Check Configuration (13 NOV 2025)
    # ========================================================================

    enable_database_health_check: bool = Field(
        default=True,
        description="Enable PostgreSQL connectivity checks in health endpoint"
    )

    enable_duckdb_health_check: bool = Field(
        default=False,
        description="Enable DuckDB analytical engine checks in health endpoint. "
                    "Adds ~200-500ms overhead. Disable for faster health pings (B3 tier)."
    )

    enable_vsi_health_check: bool = Field(
        default=False,
        description="Enable VSI (Virtual File System) /vsicurl/ checks in health endpoint. "
                    "Adds ~500-1000ms overhead (SAS token + file open). Disable for faster health pings (B3 tier)."
    )

    vsi_test_file: str = Field(
        default="dctest.tif",
        description="Test file name for VSI /vsicurl/ capability check in health endpoint"
    )

    vsi_test_container: str = Field(
        default="rmhazuregeobronze",
        description="Container name for VSI test file (legacy flat name)"
    )

    # ========================================================================
    # API Endpoint Configuration (3 NOV 2025)
    # ========================================================================

    titiler_base_url: str = Field(
        default="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net",
        description="Base URL for TiTiler-PgSTAC tile server (raster visualization)"
    )

    ogc_features_base_url: str = Field(
        default="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features",
        description="Base URL for OGC API - Features (vector data access)"
    )

    titiler_mode: str = Field(
        default="pgstac",
        description="TiTiler deployment mode (vanilla, pgstac, xarray)",
        examples=["vanilla", "pgstac", "xarray"]
    )

    # ========================================================================
    # Key Vault Configuration (DEPRECATED - Using env vars)
    # ========================================================================

    key_vault_name: Optional[str] = Field(
        default=None,
        description="DEPRECATED: Azure Key Vault name (using environment variables instead)",
        deprecated="Using environment variables for secrets instead of Key Vault"
    )

    key_vault_database_secret: str = Field(
        default="postgis-password",
        description="DEPRECATED: Key Vault secret name for PostgreSQL password",
        deprecated="Using POSTGIS_PASSWORD environment variable"
    )

    # ========================================================================
    # Domain Configurations (Composition Pattern)
    # ========================================================================

    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="Multi-account storage configuration for trust zones (Bronze/Silver/SilverExternal/Gold)"
    )

    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig.from_environment,
        description="PostgreSQL/PostGIS configuration with managed identity support"
    )

    raster: RasterConfig = Field(
        default_factory=RasterConfig.from_environment,
        description="Raster processing pipeline configuration"
    )

    vector: VectorConfig = Field(
        default_factory=VectorConfig.from_environment,
        description="Vector processing pipeline configuration"
    )

    queues: QueueConfig = Field(
        default_factory=QueueConfig.from_environment,
        description="Azure Service Bus queue configuration"
    )

    # ========================================================================
    # Legacy Compatibility Properties (During Migration)
    # ========================================================================
    # These delegate to domain configs for backward compatibility
    # Will be removed after migration is complete

    @property
    def postgis_host(self) -> str:
        """Legacy compatibility - use database.host instead."""
        return self.database.host

    @property
    def postgis_port(self) -> int:
        """Legacy compatibility - use database.port instead."""
        return self.database.port

    @property
    def postgis_user(self) -> str:
        """Legacy compatibility - use database.user instead."""
        return self.database.user

    @property
    def postgis_password(self) -> Optional[str]:
        """Legacy compatibility - use database.password instead."""
        return self.database.password

    @property
    def postgis_database(self) -> str:
        """Legacy compatibility - use database.database instead."""
        return self.database.database

    @property
    def postgis_schema(self) -> str:
        """Legacy compatibility - use database.postgis_schema instead."""
        return self.database.postgis_schema

    @property
    def app_schema(self) -> str:
        """Legacy compatibility - use database.app_schema instead."""
        return self.database.app_schema

    @property
    def raster_cog_compression(self) -> str:
        """Legacy compatibility - use raster.cog_compression instead."""
        return self.raster.cog_compression

    @property
    def raster_cog_tile_size(self) -> int:
        """Legacy compatibility - use raster.cog_tile_size instead."""
        return self.raster.cog_tile_size

    @property
    def vector_pickle_container(self) -> str:
        """Legacy compatibility - use vector.pickle_container instead."""
        return self.vector.pickle_container

    @property
    def vector_pickle_prefix(self) -> str:
        """Legacy compatibility - use vector.pickle_prefix instead."""
        return self.vector.pickle_prefix

    @property
    def job_processing_queue(self) -> str:
        """Legacy compatibility - use queues.jobs_queue instead."""
        return self.queues.jobs_queue

    @property
    def task_processing_queue(self) -> str:
        """Legacy compatibility - use queues.tasks_queue instead."""
        return self.queues.tasks_queue

    @property
    def blob_service_url(self) -> str:
        """Azure Blob Storage service URL for managed identity."""
        return f"https://{self.storage_account_name}.blob.core.windows.net"

    @property
    def queue_service_url(self) -> str:
        """Azure Queue Storage service URL for managed identity."""
        return f"https://{self.storage_account_name}.queue.core.windows.net"

    @property
    def table_service_url(self) -> str:
        """Azure Table Storage service URL for managed identity."""
        return f"https://{self.storage_account_name}.table.core.windows.net"

    @property
    def service_bus_jobs_queue(self) -> str:
        """Legacy compatibility - use queues.jobs_queue instead."""
        return self.queues.jobs_queue

    @property
    def service_bus_tasks_queue(self) -> str:
        """Legacy compatibility - use queues.tasks_queue instead."""
        return self.queues.tasks_queue

    @property
    def service_bus_namespace(self) -> Optional[str]:
        """Legacy compatibility - use queues.namespace instead."""
        return self.queues.namespace

    @property
    def service_bus_connection_string(self) -> Optional[str]:
        """Legacy compatibility - use queues.connection_string instead."""
        return self.queues.connection_string

    @property
    def service_bus_max_batch_size(self) -> int:
        """Legacy compatibility - use queues.max_batch_size instead."""
        return self.queues.max_batch_size

    @property
    def service_bus_retry_count(self) -> int:
        """Legacy compatibility - use queues.retry_count instead."""
        return self.queues.retry_count

    @property
    def postgis_connection_string(self) -> str:
        """Legacy compatibility - use database.connection_string instead."""
        return self.database.connection_string

    @classmethod
    def from_environment(cls):
        """Load all configs from environment."""
        return cls(
            # Core settings
            debug_mode=os.environ.get("DEBUG_MODE", "false").lower() == "true",
            environment=os.environ.get("ENVIRONMENT", "dev"),
            storage_account_name=os.environ.get("STORAGE_ACCOUNT_NAME", "rmhazuregeo"),
            bronze_container_name=os.environ.get("BRONZE_CONTAINER_NAME", "rmhazuregeobronze"),
            silver_container_name=os.environ.get("SILVER_CONTAINER_NAME", "rmhazuregeosilver"),
            gold_container_name=os.environ.get("GOLD_CONTAINER_NAME", "rmhazuregeogold"),
            function_timeout_minutes=int(os.environ.get("FUNCTION_TIMEOUT_MINUTES", "30")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),

            # Domain configs
            storage=StorageConfig.from_environment(),
            database=DatabaseConfig.from_environment(),
            raster=RasterConfig.from_environment(),
            vector=VectorConfig.from_environment(),
            queues=QueueConfig.from_environment()
        )
