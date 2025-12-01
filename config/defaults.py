# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION DEFAULTS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New module - Single source of truth for all defaults (30 NOV 2025)
# PURPOSE: Centralize ALL hardcoded default values in one file
# LAST_REVIEWED: 30 NOV 2025
# EXPORTS: AzureDefaults, DatabaseDefaults, StorageDefaults, QueueDefaults,
#          RasterDefaults, VectorDefaults, AnalyticsDefaults, H3Defaults,
#          PlatformDefaults, AppDefaults
# INTERFACES: Pure Python classes (no Pydantic - just constants)
# PYDANTIC_MODELS: None - consumed by Pydantic config classes
# DEPENDENCIES: None (intentionally dependency-free)
# SOURCE: Static values - no env vars read here
# SCOPE: Global defaults for entire application
# VALIDATION: None - config classes handle validation
# PATTERNS: Constants classes, single source of truth
# ENTRY_POINTS: from config.defaults import AzureDefaults, DatabaseDefaults, ...
# INDEX: AzureDefaults:40, DatabaseDefaults:60, StorageDefaults:80,
#        QueueDefaults:120, RasterDefaults:140, VectorDefaults:180,
#        AnalyticsDefaults:200, H3Defaults:220, PlatformDefaults:240,
#        AppDefaults:280
# ============================================================================

"""
SINGLE SOURCE OF TRUTH for all default values.

When deploying to a new Azure tenant, review this file to understand
what environment variables must be set vs what can use defaults.

Organization:
    - AzureDefaults: Values that MUST be overridden for new tenant deployment
    - *Defaults: Safe defaults that work for any deployment

Usage:
    from config.defaults import DatabaseDefaults, AzureDefaults

    # In Pydantic Field definitions:
    port: int = Field(default=DatabaseDefaults.PORT, ...)

    # In deployment validation:
    if config.storage_account_name == AzureDefaults.STORAGE_ACCOUNT_NAME:
        issues.append("Storage account not configured for this tenant")

Created: 30 NOV 2025 as part of config centralization refactor
Author: Robert and Geospatial Claude Legion
"""


# =============================================================================
# AZURE RESOURCE DEFAULTS (MUST override for new tenant)
# =============================================================================

class AzureDefaults:
    """
    Defaults that MUST be overridden for a new Azure tenant deployment.

    These values are specific to the development tenant (rmhazure_rg).
    When deploying to a new tenant, ALL of these must be set via environment variables.

    The health endpoint uses these to detect if deployment is properly configured.
    """

    # Storage Account - Override: STORAGE_ACCOUNT_NAME
    STORAGE_ACCOUNT_NAME = "rmhazuregeo"

    # Managed Identity - Override: MANAGED_IDENTITY_NAME
    MANAGED_IDENTITY_NAME = "rmhpgflexadmin"

    # TiTiler tile server - Override: TITILER_BASE_URL
    TITILER_BASE_URL = "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

    # OGC/STAC API - Override: OGC_STAC_APP_URL
    OGC_STAC_APP_URL = "https://rmhogcstac-b4f5ccetf0a7hwe9.eastus-01.azurewebsites.net"

    # ETL/Admin Function App - Override: ETL_APP_URL
    ETL_APP_URL = "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"


# =============================================================================
# DATABASE DEFAULTS (Safe for any deployment)
# =============================================================================

class DatabaseDefaults:
    """
    Database configuration defaults - safe for any deployment.

    These are standard PostgreSQL/PostGIS settings that work universally.
    """

    PORT = 5432
    POSTGIS_SCHEMA = "geo"
    APP_SCHEMA = "app"
    PGSTAC_SCHEMA = "pgstac"
    H3_SCHEMA = "h3"
    CONNECTION_TIMEOUT_SECONDS = 30
    MIN_CONNECTIONS = 1
    MAX_CONNECTIONS = 20


# =============================================================================
# STORAGE DEFAULTS (Safe patterns)
# =============================================================================

class StorageDefaults:
    """
    Storage container naming defaults - safe patterns for any deployment.

    Container names follow the pattern: {tier}-{purpose}
    These can be overridden per-container if needed.
    """

    # Bronze tier containers (raw uploads)
    BRONZE_VECTORS = "bronze-vectors"
    BRONZE_RASTERS = "bronze-rasters"
    BRONZE_MISC = "bronze-misc"
    BRONZE_TEMP = "bronze-temp"

    # Silver tier containers (processed data)
    SILVER_VECTORS = "silver-vectors"
    SILVER_RASTERS = "silver-rasters"
    SILVER_COGS = "silver-cogs"
    SILVER_TILES = "silver-tiles"
    SILVER_MOSAICJSON = "silver-mosaicjson"
    SILVER_STAC_ASSETS = "silver-stac-assets"
    SILVER_MISC = "silver-misc"
    SILVER_TEMP = "silver-temp"

    # SilverExt tier (airgapped external)
    SILVEREXT_VECTORS = "silverext-vectors"
    SILVEREXT_RASTERS = "silverext-rasters"
    SILVEREXT_COGS = "silverext-cogs"
    SILVEREXT_TILES = "silverext-tiles"
    SILVEREXT_MOSAICJSON = "silverext-mosaicjson"
    SILVEREXT_STAC_ASSETS = "silverext-stac-assets"
    SILVEREXT_MISC = "silverext-misc"
    SILVEREXT_TEMP = "silverext-temp"

    # Gold tier containers (analytics exports)
    GOLD_GEOPARQUET = "gold-geoparquet"
    GOLD_H3_GRIDS = "gold-h3-grids"
    GOLD_TEMP = "gold-temp"

    # Placeholder for unused container slots
    NOT_USED = "notused"


# =============================================================================
# QUEUE DEFAULTS (Service Bus)
# =============================================================================

class QueueDefaults:
    """
    Service Bus queue defaults.

    Note: This is a SERVICE BUS ONLY application.
    Storage Queues are NOT supported.
    """

    JOBS_QUEUE = "geospatial-jobs"
    TASKS_QUEUE = "geospatial-tasks"
    MAX_BATCH_SIZE = 100
    BATCH_THRESHOLD = 50
    RETRY_COUNT = 3


# =============================================================================
# RASTER DEFAULTS (COG processing)
# =============================================================================

class RasterDefaults:
    """
    Raster processing pipeline defaults.

    Controls COG creation, validation, and MosaicJSON generation.
    """

    # Size thresholds
    SIZE_THRESHOLD_MB = 1000  # 1 GB - small vs large file cutoff
    MAX_FILE_SIZE_MB = 20000  # 20 GB - maximum allowed file size
    IN_MEMORY_THRESHOLD_MB = 500  # 500 MB - in-memory vs disk processing

    # COG creation
    COG_COMPRESSION = "deflate"
    COG_JPEG_QUALITY = 85
    COG_TILE_SIZE = 512
    COG_IN_MEMORY = False  # Disk-based safer with concurrency

    # Reprojection and validation
    TARGET_CRS = "EPSG:4326"
    OVERVIEW_RESAMPLING = "average"
    REPROJECT_RESAMPLING = "bilinear"
    STRICT_VALIDATION = True

    # MosaicJSON
    MOSAICJSON_MAXZOOM = 19

    # STAC
    STAC_DEFAULT_COLLECTION = "system-rasters"

    # Intermediate storage
    INTERMEDIATE_PREFIX = "temp/raster_etl"


# =============================================================================
# VECTOR DEFAULTS (PostGIS ETL)
# =============================================================================

class VectorDefaults:
    """
    Vector processing pipeline defaults.

    Controls chunked vector processing, PostGIS uploads, and spatial indexing.
    """

    PICKLE_CONTAINER = "rmhazuregeotemp"
    PICKLE_PREFIX = "temp/vector_etl"
    DEFAULT_CHUNK_SIZE = 1000
    AUTO_CHUNK_SIZING = True
    TARGET_SCHEMA = "geo"
    CREATE_SPATIAL_INDEXES = True


# =============================================================================
# ANALYTICS DEFAULTS (DuckDB)
# =============================================================================

class AnalyticsDefaults:
    """
    DuckDB and columnar analytics defaults.

    Controls DuckDB connection, extensions, and performance tuning.
    """

    CONNECTION_TYPE = "memory"
    ENABLE_SPATIAL = True
    ENABLE_AZURE = True
    ENABLE_HTTPFS = True
    MEMORY_LIMIT = "4GB"
    THREADS = 4


# =============================================================================
# H3 DEFAULTS (Spatial indexing)
# =============================================================================

class H3Defaults:
    """
    H3 hexagonal spatial indexing defaults.

    Controls H3 grid generation and spatial filtering.
    """

    SYSTEM_ADMIN0_TABLE = "geo.system_admin0"
    SPATIAL_FILTER_TABLE = "system_admin0"
    DEFAULT_RESOLUTION = 4  # ~1,770 km² per cell
    ENABLE_LAND_FILTER = True


# =============================================================================
# PLATFORM DEFAULTS (DDH integration)
# =============================================================================

class PlatformDefaults:
    """
    Platform layer defaults for DDH integration.

    Controls anti-corruption layer between DDH and CoreMachine.
    """

    PRIMARY_CLIENT = "ddh"
    DEFAULT_ACCESS_LEVEL = "OUO"
    VALID_ACCESS_LEVELS = ["public", "OUO", "restricted"]
    VALID_INPUT_CONTAINERS = [
        "bronze-vectors",
        "bronze-rasters",
        "bronze-misc",
        "bronze-temp",
    ]

    # Naming patterns (use placeholders: {dataset_id}, {resource_id}, {version_id})
    VECTOR_TABLE_PATTERN = "{dataset_id}_{resource_id}_{version_id}"
    RASTER_OUTPUT_FOLDER_PATTERN = "{dataset_id}/{resource_id}/{version_id}"
    STAC_COLLECTION_PATTERN = "{dataset_id}"
    STAC_ITEM_PATTERN = "{dataset_id}_{resource_id}_{version_id}"

    # Request ID generation
    REQUEST_ID_LENGTH = 32

    # Webhooks (future)
    WEBHOOK_ENABLED = False
    WEBHOOK_RETRY_COUNT = 3
    WEBHOOK_RETRY_DELAY_SECONDS = 5


# =============================================================================
# APPLICATION DEFAULTS
# =============================================================================

class AppDefaults:
    """
    Application-wide defaults.

    Controls debug mode, logging, health checks, and timeouts.
    """

    # Environment
    DEBUG_MODE = False
    ENVIRONMENT = "dev"
    LOG_LEVEL = "INFO"

    # Timeouts and retries
    FUNCTION_TIMEOUT_MINUTES = 30
    TASK_MAX_RETRIES = 3
    TASK_RETRY_BASE_DELAY = 5  # seconds
    TASK_RETRY_MAX_DELAY = 300  # 5 minutes
    MAX_RETRIES = 3

    # Health checks
    ENABLE_DATABASE_HEALTH_CHECK = True
    ENABLE_DUCKDB_HEALTH_CHECK = False  # Adds ~200-500ms overhead
    ENABLE_VSI_HEALTH_CHECK = False  # Adds ~500-1000ms overhead
    VSI_TEST_FILE = "dctest.tif"
    VSI_TEST_CONTAINER = "rmhazuregeobronze"

    # TiTiler
    TITILER_MODE = "pgstac"


# =============================================================================
# KEY VAULT DEFAULTS (Keep for future use)
# =============================================================================

class KeyVaultDefaults:
    """
    Key Vault defaults - kept for potential future use.

    Currently using environment variables for secrets.
    Key Vault integration may be re-enabled for certain deployments.
    """

    DATABASE_SECRET_NAME = "postgis-password"


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "AzureDefaults",
    "DatabaseDefaults",
    "StorageDefaults",
    "QueueDefaults",
    "RasterDefaults",
    "VectorDefaults",
    "AnalyticsDefaults",
    "H3Defaults",
    "PlatformDefaults",
    "AppDefaults",
    "KeyVaultDefaults",
]
