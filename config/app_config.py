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
from .analytics_config import AnalyticsConfig
from .h3_config import H3Config
from .platform_config import PlatformConfig


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
        default="https://rmhogcstac-b4f5ccetf0a7hwe9.eastus-01.azurewebsites.net/api/features",
        description="Base URL for OGC API - Features (vector data access) - Dedicated OGC/STAC function app"
    )

    stac_api_base_url: str = Field(
        default="https://rmhogcstac-b4f5ccetf0a7hwe9.eastus-01.azurewebsites.net/api/stac",
        description="Base URL for STAC API (metadata catalog) - Currently co-located with OGC Features, can be separated later"
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

    analytics: AnalyticsConfig = Field(
        default_factory=AnalyticsConfig.from_environment,
        description="DuckDB and columnar analytics configuration (GeoParquet exports)"
    )

    h3: H3Config = Field(
        default_factory=H3Config.from_environment,
        description="H3 spatial indexing system configuration"
    )

    platform: PlatformConfig = Field(
        default_factory=PlatformConfig.from_environment,
        description="Platform layer configuration (DDH integration, anti-corruption layer)"
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
    def raster_cog_in_memory(self) -> bool:
        """Legacy compatibility - use raster.cog_in_memory instead."""
        return self.raster.cog_in_memory

    @property
    def raster_target_crs(self) -> str:
        """Legacy compatibility - use raster.target_crs instead."""
        return self.raster.target_crs

    @property
    def raster_mosaicjson_maxzoom(self) -> int:
        """Legacy compatibility - use raster.mosaicjson_maxzoom instead."""
        return self.raster.mosaicjson_maxzoom

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

    # H3 legacy properties
    @property
    def system_admin0_table(self) -> str:
        """Legacy compatibility - use h3.system_admin0_table instead."""
        return self.h3.system_admin0_table

    @property
    def h3_spatial_filter_table(self) -> str:
        """Legacy compatibility - use h3.spatial_filter_table instead."""
        return self.h3.spatial_filter_table

    # DuckDB/Analytics legacy properties
    @property
    def duckdb_connection_type(self) -> str:
        """Legacy compatibility - use analytics.connection_type instead."""
        return self.analytics.connection_type.value

    @property
    def duckdb_database_path(self) -> Optional[str]:
        """Legacy compatibility - use analytics.database_path instead."""
        return self.analytics.database_path

    @property
    def duckdb_enable_spatial(self) -> bool:
        """Legacy compatibility - use analytics.enable_spatial instead."""
        return self.analytics.enable_spatial

    @property
    def duckdb_enable_azure(self) -> bool:
        """Legacy compatibility - use analytics.enable_azure instead."""
        return self.analytics.enable_azure

    @property
    def duckdb_enable_httpfs(self) -> bool:
        """Legacy compatibility - use analytics.enable_httpfs instead."""
        return self.analytics.enable_httpfs

    @property
    def duckdb_memory_limit(self) -> str:
        """Legacy compatibility - use analytics.memory_limit instead."""
        return self.analytics.memory_limit

    @property
    def duckdb_threads(self) -> int:
        """Legacy compatibility - use analytics.threads instead."""
        return self.analytics.threads

    @property
    def intermediate_tiles_container(self) -> Optional[str]:
        """Legacy compatibility - use raster.intermediate_tiles_container instead."""
        return self.raster.intermediate_tiles_container

    @property
    def resolved_intermediate_tiles_container(self) -> str:
        """
        Get intermediate tiles container, defaulting to silver-mosaicjson if not specified.

        UPDATED (12 NOV 2025): Changed default from "silver-tiles" to "silver-mosaicjson"
        to separate MosaicJSON files from other tile data.

        Returns container name for MosaicJSON files (Stage 3 output).
        If intermediate_tiles_container is None, falls back to silver-mosaicjson.

        Usage:
            config = get_config()
            container = config.resolved_intermediate_tiles_container
            # Returns: "silver-mosaicjson" (or custom value if env var set)
        """
        return self.raster.intermediate_tiles_container or "silver-mosaicjson"

    @property
    def titiler_pgstac_base_url(self) -> str:
        """Legacy compatibility - same as titiler_base_url for pgstac mode."""
        return self.titiler_base_url

    # ========================================================================
    # URL Generation Methods (Legacy Compatibility)
    # ========================================================================

    def generate_ogc_features_url(self, collection_id: str) -> str:
        """
        Generate OGC API - Features collection URL for vector data.

        Legacy compatibility method - delegates to ogc_features_base_url field.

        Args:
            collection_id: Collection name (same as PostGIS table name)

        Returns:
            OGC Features collection URL for querying vector features

        Example:
            >>> config = get_config()
            >>> url = config.generate_ogc_features_url("config_test_vector")
            >>> url
            'https://rmhazuregeoapi-.../api/features/collections/config_test_vector'
        """
        return f"{self.ogc_features_base_url.rstrip('/')}/collections/{collection_id}"

    def generate_vector_viewer_url(self, collection_id: str) -> str:
        """
        Generate interactive vector viewer URL for PostGIS collection.

        Legacy compatibility method - derives from ogc_features_base_url.

        Args:
            collection_id: Collection name (same as PostGIS table name)

        Returns:
            Vector viewer URL for interactive map visualization
        """
        # Extract base URL from ogc_features_base_url (remove /api/features suffix)
        base_url = self.ogc_features_base_url.rstrip('/')
        if base_url.endswith('/api/features'):
            base_url = base_url[:-len('/api/features')]
        return f"{base_url}/api/vector/viewer?collection={collection_id}"

    def generate_titiler_urls(self, collection_id: str, item_id: str) -> dict:
        """
        Generate TiTiler-PgSTAC URLs for raster visualization.

        Legacy compatibility method - uses titiler_pgstac_base_url field.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID

        Returns:
            Dictionary with TiTiler endpoint URLs
        """
        base = self.titiler_pgstac_base_url.rstrip('/')
        return {
            "info": f"{base}/info?collection={collection_id}&item={item_id}",
            "tilejson": f"{base}/tilejson.json?collection={collection_id}&item={item_id}",
            "viewer": f"{base}/viewer?collection={collection_id}&item={item_id}",
            "preview": f"{base}/preview.png?collection={collection_id}&item={item_id}"
        }

    def generate_titiler_urls_unified(
        self,
        mode: str,
        container: str = None,
        blob_name: str = None,
        search_id: str = None
    ) -> dict:
        """
        Generate TiTiler URLs for all three access patterns.

        Consolidates three TiTiler visualization patterns into single method:
        1. Single COG - Direct /vsiaz/ access to individual raster
        2. MosaicJSON - Collection of COGs as single layer
        3. PgSTAC Search - Dynamic queries across STAC catalog

        Args:
            mode: URL generation mode ('cog', 'mosaicjson', 'pgstac')
            container: Azure container name (required for cog/mosaicjson modes)
            blob_name: Blob path within container (required for cog/mosaicjson modes)
            search_id: PgSTAC search hash (required for pgstac mode)

        Returns:
            Dict with TiTiler URLs (viewer_url, info_url, preview_url, etc.)
        """
        import urllib.parse

        base = self.titiler_base_url.rstrip('/')

        if mode == "cog":
            if not container or not blob_name:
                raise ValueError(
                    f"mode='cog' requires container and blob_name. "
                    f"Got: container={container}, blob_name={blob_name}"
                )

            vsiaz_path = f"/vsiaz/{container}/{blob_name}"
            encoded_vsiaz = urllib.parse.quote(vsiaz_path, safe='')

            return {
                "viewer_url": f"{base}/cog/WebMercatorQuad/map.html?url={encoded_vsiaz}",
                "info_url": f"{base}/cog/info?url={encoded_vsiaz}",
                "preview_url": f"{base}/cog/preview.png?url={encoded_vsiaz}&max_size=512",
                "thumbnail_url": f"{base}/cog/preview.png?url={encoded_vsiaz}&max_size=256",
                "statistics_url": f"{base}/cog/statistics?url={encoded_vsiaz}",
                "bounds_url": f"{base}/cog/bounds?url={encoded_vsiaz}",
                "info_geojson_url": f"{base}/cog/info.geojson?url={encoded_vsiaz}",
                "tilejson_url": f"{base}/cog/WebMercatorQuad/tilejson.json?url={encoded_vsiaz}",
                "tiles_url_template": f"{base}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={encoded_vsiaz}"
            }

        elif mode == "mosaicjson":
            if not container or not blob_name:
                raise ValueError(
                    f"mode='mosaicjson' requires container and blob_name. "
                    f"Got: container={container}, blob_name={blob_name}"
                )

            if not blob_name.endswith('.json'):
                raise ValueError(
                    f"mode='mosaicjson' requires blob_name to be a .json file. Got: {blob_name}"
                )

            vsiaz_path = f"/vsiaz/{container}/{blob_name}"
            encoded_vsiaz = urllib.parse.quote(vsiaz_path, safe='')

            return {
                "viewer_url": f"{base}/mosaicjson/WebMercatorQuad/map.html?url={encoded_vsiaz}",
                "info_url": f"{base}/mosaicjson/info?url={encoded_vsiaz}",
                "bounds_url": f"{base}/mosaicjson/bounds?url={encoded_vsiaz}",
                "tilejson_url": f"{base}/mosaicjson/WebMercatorQuad/tilejson.json?url={encoded_vsiaz}",
                "tiles_url_template": f"{base}/mosaicjson/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={encoded_vsiaz}",
                "assets_url_template": f"{base}/mosaicjson/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}/assets?url={encoded_vsiaz}",
                "point_url_template": f"{base}/mosaicjson/point/{{lon}},{{lat}}?url={encoded_vsiaz}"
            }

        elif mode == "pgstac":
            raise NotImplementedError(
                "PgSTAC search URL generation not yet implemented. "
                f"For now, construct URLs directly: {base}/searches/{{search_id}}/WebMercatorQuad/map.html"
            )

        else:
            raise ValueError(f"Invalid mode: {mode}. Must be one of: 'cog', 'mosaicjson', 'pgstac'")

    # ========================================================================
    # Factory Methods
    # ========================================================================

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
            queues=QueueConfig.from_environment(),
            analytics=AnalyticsConfig.from_environment(),
            h3=H3Config.from_environment(),
            platform=PlatformConfig.from_environment()
        )
