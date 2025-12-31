"""
Main Application Configuration.

Composes domain-specific configuration modules:
    - StorageConfig (COG tiers, multi-account storage)
    - DatabaseConfig (PostgreSQL/PostGIS)
    - RasterConfig (Raster pipeline)
    - VectorConfig (Vector pipeline)
    - QueueConfig (Service Bus queues)

Exports:
    AppConfig: Main configuration class
    get_config: Singleton accessor

Dependencies:
    pydantic: BaseModel for configuration validation
    config.storage_config: StorageConfig
    config.database_config: DatabaseConfig, BusinessDatabaseConfig
    config.raster_config: RasterConfig
    config.vector_config: VectorConfig
    config.queue_config: QueueConfig
    config.analytics_config: AnalyticsConfig
    config.h3_config: H3Config
    config.platform_config: PlatformConfig
    config.defaults: Default value constants

Pattern:
    Composition over inheritance - domain configs are composed, not inherited.

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
from .database_config import DatabaseConfig, BusinessDatabaseConfig
from .raster_config import RasterConfig
from .vector_config import VectorConfig
from .queue_config import QueueConfig
from .analytics_config import AnalyticsConfig
from .h3_config import H3Config
from .platform_config import PlatformConfig
from .metrics_config import MetricsConfig
from .defaults import AzureDefaults, AppDefaults, KeyVaultDefaults


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
        default=AppDefaults.DEBUG_MODE,
        description="Enable debug mode for verbose diagnostics. "
                    "WARNING: Increases logging overhead and log volume. "
                    "Features enabled: memory tracking, detailed timing, payload logging. "
                    "Set DEBUG_MODE=true in environment to enable.",
        examples=[True, False]
    )

    environment: str = Field(
        default=AppDefaults.ENVIRONMENT,
        description="Environment name (dev, qa, prod)",
        examples=["dev", "qa", "prod"]
    )

    # ========================================================================
    # Timeouts and Retries
    # ========================================================================

    function_timeout_minutes: int = Field(
        default=AppDefaults.FUNCTION_TIMEOUT_MINUTES,
        description="Function timeout in minutes (must match host.json functionTimeout)"
    )

    task_max_retries: int = Field(
        default=AppDefaults.TASK_MAX_RETRIES,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed tasks (0 = no retries)"
    )

    task_retry_base_delay: int = Field(
        default=AppDefaults.TASK_RETRY_BASE_DELAY,
        ge=1,
        le=60,
        description="Base delay in seconds for exponential backoff (first retry)"
    )

    task_retry_max_delay: int = Field(
        default=AppDefaults.TASK_RETRY_MAX_DELAY,
        ge=10,
        le=3600,
        description="Maximum delay in seconds between retries (caps exponential growth)"
    )

    max_retries: int = Field(
        default=AppDefaults.MAX_RETRIES,
        ge=1,
        le=10,
        description="Maximum retry attempts for failed operations (general)"
    )

    # ========================================================================
    # Logging Configuration
    # ========================================================================

    log_level: str = Field(
        default=AppDefaults.LOG_LEVEL,
        description="Logging level for application diagnostics",
        examples=["DEBUG", "INFO", "WARNING", "ERROR"]
    )

    # ========================================================================
    # Health Check Configuration (13 NOV 2025)
    # ========================================================================

    enable_database_health_check: bool = Field(
        default=AppDefaults.ENABLE_DATABASE_HEALTH_CHECK,
        description="Enable PostgreSQL connectivity checks in health endpoint"
    )

    enable_duckdb_health_check: bool = Field(
        default=AppDefaults.ENABLE_DUCKDB_HEALTH_CHECK,
        description="Enable DuckDB analytical engine checks in health endpoint. "
                    "Adds ~200-500ms overhead. Disable for faster health pings (B3 tier)."
    )

    enable_vsi_health_check: bool = Field(
        default=AppDefaults.ENABLE_VSI_HEALTH_CHECK,
        description="Enable VSI (Virtual File System) /vsicurl/ checks in health endpoint. "
                    "Adds ~500-1000ms overhead (SAS token + file open). Disable for faster health pings (B3 tier)."
    )

    vsi_test_file: str = Field(
        default=AppDefaults.VSI_TEST_FILE,
        description="Test file name for VSI /vsicurl/ capability check in health endpoint"
    )

    vsi_test_container: str = Field(
        default=AppDefaults.VSI_TEST_CONTAINER,
        description="Container name for VSI test file (legacy flat name)"
    )

    # ========================================================================
    # API Endpoint Configuration (27 NOV 2025)
    # ========================================================================
    # Environment Variables:
    #   TITILER_BASE_URL     - TiTiler tile server (raster visualization)
    #   OGC_STAC_APP_URL     - Dedicated OGC/STAC function app (end-user queries)
    #   ETL_APP_URL          - ETL/Admin function app (job submission, viewer, admin)
    #   TITILER_MODE         - TiTiler deployment mode (vanilla, pgstac, xarray)
    # ========================================================================

    titiler_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "TITILER_BASE_URL",
            AzureDefaults.TITILER_BASE_URL
        ),
        description="Base URL for TiTiler-PgSTAC tile server (raster visualization)"
    )

    ogc_features_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "OGC_STAC_APP_URL",
            AzureDefaults.OGC_STAC_APP_URL
        ) + "/api/features",
        description="Base URL for OGC API - Features (vector data access) - Dedicated OGC/STAC function app"
    )

    stac_api_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "OGC_STAC_APP_URL",
            AzureDefaults.OGC_STAC_APP_URL
        ) + "/api/stac",
        description="Base URL for STAC API (metadata catalog) - Currently co-located with OGC Features"
    )

    etl_app_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "ETL_APP_URL",
            AzureDefaults.ETL_APP_URL
        ),
        description="Base URL for ETL/Admin Function App (rmhazuregeoapi) - Hosts viewer, job submission, admin endpoints"
    )

    titiler_mode: str = Field(
        default_factory=lambda: os.getenv("TITILER_MODE", AppDefaults.TITILER_MODE),
        description="TiTiler deployment mode (vanilla, pgstac, xarray)",
        examples=["vanilla", "pgstac", "xarray"]
    )

    # ========================================================================
    # Key Vault Configuration (DEPRECATED - Using env vars)
    # ========================================================================

    key_vault_name: Optional[str] = Field(
        default=None,
        description="Azure Key Vault name - kept for future use when Key Vault integration is re-enabled",
        examples=["rmh-keyvault-prod"]
    )

    key_vault_database_secret: str = Field(
        default=KeyVaultDefaults.DATABASE_SECRET_NAME,
        description="Key Vault secret name for PostgreSQL password - kept for future use",
        examples=["postgis-password"]
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
        description="PostgreSQL/PostGIS configuration for app database (full DDL permissions)"
    )

    business_database: Optional[BusinessDatabaseConfig] = Field(
        default=None,
        description="""Business database configuration for ETL pipeline outputs.

        Separate database from app database with RESTRICTED permissions:
        - App Database (geopgflex): Full DDL (CREATE/DROP SCHEMA) - can nuke/rebuild
        - Business Database (geodata): CRUD only (NO DROP SCHEMA) - protected

        If not configured (BUSINESS_DB_* env vars not set), falls back to app database
        geo schema for backward compatibility during migration.

        Environment Variables:
            BUSINESS_DB_HOST, BUSINESS_DB_NAME, BUSINESS_DB_SCHEMA,
            BUSINESS_DB_MANAGED_IDENTITY_NAME (all optional - uses app db if not set)
        """
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

    metrics: MetricsConfig = Field(
        default_factory=MetricsConfig.from_environment,
        description="Pipeline observability metrics configuration (E13: 28 DEC 2025)"
    )

    # ========================================================================
    # Azure Data Factory Configuration (29 NOV 2025)
    # ========================================================================

    adf_subscription_id: Optional[str] = Field(
        default_factory=lambda: os.environ.get("ADF_SUBSCRIPTION_ID"),
        description="Azure subscription ID for Data Factory operations"
    )

    adf_resource_group: Optional[str] = Field(
        default_factory=lambda: os.environ.get("ADF_RESOURCE_GROUP", "rmhazure_rg"),
        description="Resource group containing the Data Factory instance"
    )

    adf_factory_name: Optional[str] = Field(
        default_factory=lambda: os.environ.get("ADF_FACTORY_NAME"),
        description="Azure Data Factory instance name"
    )

    def is_adf_configured(self) -> bool:
        """
        Check if Azure Data Factory is configured.

        Returns:
            True if ADF_SUBSCRIPTION_ID and ADF_FACTORY_NAME are set
        """
        return bool(self.adf_subscription_id and self.adf_factory_name)

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
    def service_bus_jobs_queue(self) -> str:
        """Legacy compatibility - use queues.jobs_queue instead."""
        return self.queues.jobs_queue

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
        Get intermediate tiles container, defaulting to silver-cogs if not specified.

        UPDATED (19 DEC 2025): Changed default from "silver-mosaicjson" to "silver-cogs"
        to store MosaicJSON files alongside COGs in the same container.

        Returns container name for MosaicJSON files (Stage 3 output).
        If intermediate_tiles_container is None, falls back to silver-cogs.

        Usage:
            config = get_config()
            container = config.resolved_intermediate_tiles_container
            # Returns: "silver-cogs" (or custom value if env var set)
        """
        return self.raster.intermediate_tiles_container or "silver-cogs"

    @property
    def titiler_pgstac_base_url(self) -> str:
        """Legacy compatibility - same as titiler_base_url for pgstac mode."""
        return self.titiler_base_url

    # ========================================================================
    # Business Database Helper Methods (29 NOV 2025)
    # ========================================================================

    def get_business_database_config(self) -> DatabaseConfig | BusinessDatabaseConfig:
        """
        Get configuration for business data operations.

        Returns BusinessDatabaseConfig if explicitly configured (BUSINESS_DB_* env vars set),
        otherwise falls back to app database for backward compatibility.

        This allows gradual migration:
        - Phase 1: No BUSINESS_DB_* vars → uses app database geo schema
        - Phase 2: Set BUSINESS_DB_* vars → uses dedicated business database

        Usage:
            from config import get_config
            config = get_config()

            # Get appropriate config for ETL outputs
            business_config = config.get_business_database_config()

            # Check if using dedicated business database
            if isinstance(business_config, BusinessDatabaseConfig):
                logger.info(f"Using business database: {business_config.database}")
            else:
                logger.info("Using app database geo schema (fallback)")

        Returns:
            BusinessDatabaseConfig if configured, DatabaseConfig otherwise
        """
        if self.business_database and self.business_database.is_configured:
            return self.business_database
        return self.database

    def is_business_database_configured(self) -> bool:
        """
        Check if dedicated business database is configured.

        Returns:
            True if BUSINESS_DB_HOST or BUSINESS_DB_NAME environment variables are set
        """
        return self.business_database is not None and self.business_database.is_configured

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

        Uses ETL app (rmhazuregeoapi) for viewer - admin/curation functionality.
        End-user queries go through rmhogcstac (OGC Features API).

        Args:
            collection_id: Collection name (same as PostGIS table name)

        Returns:
            Vector viewer URL for interactive map visualization (ETL app)
        """
        # Viewer is hosted on ETL app, not OGC/STAC app (27 NOV 2025)
        return f"{self.etl_app_base_url.rstrip('/')}/api/vector/viewer?collection={collection_id}"

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
    # Debug Mode Helper Methods (07 DEC 2025)
    # ========================================================================

    def get_debug_status(self) -> dict:
        """
        Get comprehensive debug mode status for diagnostics (07 DEC 2025).

        Returns a summary of all debug-related settings and what features
        they enable. Used by health endpoint and diagnostic endpoints.

        Returns:
            {
                "debug_mode": true/false,
                "debug_logging": true/false,
                "environment": "dev/qa/prod",
                "features_enabled": [...],
                "log_level": "DEBUG/INFO/..."
            }
        """
        import os

        debug_mode = self.debug_mode
        debug_logging = os.environ.get("DEBUG_LOGGING", "false").lower() == "true"

        features_enabled = []
        if debug_mode:
            features_enabled.extend([
                "memory_tracking",
                "detailed_timing",
                "config_sources_in_health",
                "verbose_validation_messages",
                "parameter_origin_logging",
                "full_parameter_dumps_on_failure"
            ])
        if debug_logging:
            features_enabled.extend([
                "debug_log_level",
                "verbose_sql_logging",
                "request_payload_logging"
            ])

        return {
            "debug_mode": debug_mode,
            "debug_logging": debug_logging,
            "environment": self.environment,
            "log_level": self.log_level,
            "features_enabled": features_enabled,
            "is_production": self.environment == "prod",
            "verbose_enabled": debug_mode or debug_logging
        }

    def should_log_verbose(self) -> bool:
        """
        Check if verbose logging should be enabled (07 DEC 2025).

        Returns True if either DEBUG_MODE or DEBUG_LOGGING is enabled.
        Use this to guard verbose logging statements.

        Usage:
            config = get_config()
            if config.should_log_verbose():
                logger.debug(f"Detailed info: {extensive_data}")
        """
        import os
        debug_logging = os.environ.get("DEBUG_LOGGING", "false").lower() == "true"
        return self.debug_mode or debug_logging

    # ========================================================================
    # Factory Methods
    # ========================================================================

    @classmethod
    def from_environment(cls):
        """Load all configs from environment."""
        return cls(
            # Core settings (using defaults from config/defaults.py)
            debug_mode=os.environ.get("DEBUG_MODE", str(AppDefaults.DEBUG_MODE).lower()).lower() == "true",
            environment=os.environ.get("ENVIRONMENT", AppDefaults.ENVIRONMENT),
            function_timeout_minutes=int(os.environ.get("FUNCTION_TIMEOUT_MINUTES", str(AppDefaults.FUNCTION_TIMEOUT_MINUTES))),
            log_level=os.environ.get("LOG_LEVEL", AppDefaults.LOG_LEVEL),

            # Domain configs
            storage=StorageConfig.from_environment(),
            database=DatabaseConfig.from_environment(),
            # Business database: only instantiate if explicitly configured
            business_database=BusinessDatabaseConfig.from_environment()
                if (os.environ.get("BUSINESS_DB_HOST") or os.environ.get("BUSINESS_DB_NAME"))
                else None,
            raster=RasterConfig.from_environment(),
            vector=VectorConfig.from_environment(),
            queues=QueueConfig.from_environment(),
            analytics=AnalyticsConfig.from_environment(),
            h3=H3Config.from_environment(),
            platform=PlatformConfig.from_environment()
        )
