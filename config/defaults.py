"""
Configuration Defaults - Single source of truth for all default values.

FAIL-FAST DESIGN (12 DEC 2025):
Tenant-specific defaults use INTENTIONALLY INVALID placeholder values.
This ensures deployments fail loudly if required environment variables aren't set.

Organization:
    - AzureDefaults: MUST be overridden - uses invalid placeholders (fail-fast)
    - StorageDefaults.DEFAULT_ACCOUNT_NAME: MUST be overridden (fail-fast)
    - AppModeDefaults.DEFAULT_APP_NAME: MUST be overridden (fail-fast)
    - All other *Defaults: Safe universal defaults that work for any deployment

Required Environment Variables (will fail if not set):
    DB_ADMIN_MANAGED_IDENTITY_NAME - PostgreSQL managed identity name
    TITILER_BASE_URL - TiTiler tile server URL
    OGC_STAC_APP_URL - OGC/STAC API URL
    ETL_APP_URL - ETL/Admin Function App URL
    BRONZE_STORAGE_ACCOUNT - Bronze zone storage account name
    SILVER_STORAGE_ACCOUNT - Silver zone storage account name
    APP_NAME - Function App name for task tracking

Usage:
    from config.defaults import DatabaseDefaults, AzureDefaults

    # In Pydantic Field definitions:
    port: int = Field(default=DatabaseDefaults.PORT, ...)

    # Fail-fast validation example:
    if config.storage.bronze.account_name == StorageDefaults.DEFAULT_ACCOUNT_NAME:
        raise ValueError("BRONZE_STORAGE_ACCOUNT environment variable not set!")
"""


# =============================================================================
# AZURE RESOURCE DEFAULTS (MUST override for new tenant)
# =============================================================================

class AzureDefaults:
    """
    Defaults that MUST be overridden for a new Azure tenant deployment.

    FAIL-FAST DESIGN (12 DEC 2025):
    These defaults are INTENTIONALLY INVALID to cause loud failures if not overridden.
    If you see errors referencing these placeholder values, you need to set the
    corresponding environment variables for your deployment.

    Required Environment Variables:
        DB_ADMIN_MANAGED_IDENTITY_NAME - PostgreSQL managed identity name
        TITILER_BASE_URL - TiTiler tile server URL
        OGC_STAC_APP_URL - OGC/STAC API URL (or same as ETL_APP_URL for standalone)
        ETL_APP_URL - ETL/Admin Function App URL
    """

    # Managed Identity (Admin) - Override: DB_ADMIN_MANAGED_IDENTITY_NAME
    # Single identity used for ALL database operations (ETL, OGC/STAC, TiTiler)
    # Simplifies architecture - no separate reader identity needed
    MANAGED_IDENTITY_NAME = "your-managed-identity-name"

    # TiTiler tile server - Override: TITILER_BASE_URL
    TITILER_BASE_URL = "https://your-titiler-webapp-url"

    # OGC/STAC API - Override: OGC_STAC_APP_URL
    OGC_STAC_APP_URL = "https://your-ogc-stac-app-url"

    # ETL/Admin Function App - Override: ETL_APP_URL
    ETL_APP_URL = "https://your-etl-app-url"


# =============================================================================
# DATABASE DEFAULTS (Safe for any deployment)
# =============================================================================

class DatabaseDefaults:
    """
    Database configuration reference values.

    IMPORTANT (23 DEC 2025): Schema names REQUIRE explicit environment variables.
    These constants are for reference only - NOT used as fallback defaults.

    Required environment variables:
    - POSTGIS_SCHEMA (standard value: 'geo')
    - APP_SCHEMA (standard value: 'app')
    - PGSTAC_SCHEMA (standard value: 'pgstac')
    - H3_SCHEMA (standard value: 'h3')
    """

    PORT = 5432
    # Schema names - reference values only, env vars REQUIRED
    POSTGIS_SCHEMA = "geo"      # Set POSTGIS_SCHEMA env var
    APP_SCHEMA = "app"          # Set APP_SCHEMA env var
    PGSTAC_SCHEMA = "pgstac"    # Set PGSTAC_SCHEMA env var
    H3_SCHEMA = "h3"            # Set H3_SCHEMA env var
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

    Storage accounts should be set per-zone:
        BRONZE_STORAGE_ACCOUNT, SILVER_STORAGE_ACCOUNT, etc.
    """

    # Default storage account (INTENTIONALLY INVALID - must be overridden)
    DEFAULT_ACCOUNT_NAME = "your-storage-account-name"

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
    SILVER_MOSAICJSON = "silver-cogs"  # MosaicJSON stored alongside COGs (15 DEC 2025)
    SILVER_STAC_ASSETS = "silver-cogs"  # Consolidated into silver-cogs (15 DEC 2025)
    SILVER_MISC = "silver-cogs"  # Consolidated into silver-cogs (15 DEC 2025)
    SILVER_TEMP = "silver-temp"

    # SilverExt tier (airgapped external)
    SILVEREXT_VECTORS = "silverext-vectors"
    SILVEREXT_RASTERS = "silverext-rasters"
    SILVEREXT_COGS = "silverext-cogs"
    SILVEREXT_TILES = "silverext-tiles"
    SILVEREXT_MOSAICJSON = "silverext-cogs"  # MosaicJSON stored alongside COGs (19 DEC 2025)
    SILVEREXT_STAC_ASSETS = "silverext-cogs"  # Consolidated into silverext-cogs (19 DEC 2025)
    SILVEREXT_MISC = "silverext-cogs"  # Consolidated into silverext-cogs (19 DEC 2025)
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

    Queue Architecture (11 DEC 2025 - No Legacy Fallbacks):
    - geospatial-jobs: Job orchestration (Platform apps listen)
    - raster-tasks: Raster task processing (memory-intensive GDAL ops)
    - vector-tasks: Vector task processing (high-concurrency DB ops)
    - long-running-raster-tasks: Docker worker processing (13 DEC 2025 placeholder)

    All task types MUST be explicitly mapped in TaskRoutingDefaults.
    Unmapped task types will raise ContractViolationError (no fallback).
    """

    JOBS_QUEUE = "geospatial-jobs"
    RASTER_TASKS_QUEUE = "raster-tasks"   # Raster-optimized queue
    VECTOR_TASKS_QUEUE = "vector-tasks"   # Vector-optimized queue

    # Long-running tasks for Docker worker (13 DEC 2025, renamed 22 DEC 2025)
    # When Docker support is added, large tasks route here (no timeout constraints)
    LONG_RUNNING_TASKS_QUEUE = "long-running-tasks"

    MAX_BATCH_SIZE = 100
    BATCH_THRESHOLD = 50
    RETRY_COUNT = 3


# =============================================================================
# APP MODE DEFAULTS (Multi-Function App Architecture)
# =============================================================================

class AppModeDefaults:
    """
    Application deployment mode configuration.

    Controls which queues this app listens to and how tasks are routed.
    Enables single codebase to be deployed in different configurations.

    Architecture (07 DEC 2025, updated 22 DEC 2025):
    - Centralized orchestration: Platform app handles jobs queue
    - Distributed execution: Workers process task queues
    - Message-based signaling: Workers send stage_complete to jobs queue
    - Docker workers: Long-running tasks without Azure Functions timeout constraints
    """

    # Valid modes
    STANDALONE = "standalone"           # All queues, all endpoints (current behavior)
    PLATFORM_RASTER = "platform_raster" # HTTP + jobs + raster-tasks
    PLATFORM_VECTOR = "platform_vector" # HTTP + jobs + vector-tasks
    PLATFORM_ONLY = "platform_only"     # HTTP + jobs only (pure router)
    WORKER_RASTER = "worker_raster"     # raster-tasks only
    WORKER_VECTOR = "worker_vector"     # vector-tasks only
    WORKER_DOCKER = "worker_docker"     # long-running-raster-tasks only (Docker container)

    VALID_MODES = [
        STANDALONE, PLATFORM_RASTER, PLATFORM_VECTOR,
        PLATFORM_ONLY, WORKER_RASTER, WORKER_VECTOR, WORKER_DOCKER
    ]

    DEFAULT_MODE = STANDALONE
    # App name used for task tracking (INTENTIONALLY INVALID - set APP_NAME env var)
    DEFAULT_APP_NAME = "your-function-app-name"


# =============================================================================
# TASK ROUTING DEFAULTS (Task Type → Queue Mapping)
# =============================================================================

class TaskRoutingDefaults:
    """
    Task type to queue category mapping.

    Maps task_type → routing category (raster, vector, long-running).
    CoreMachine uses this to route tasks to appropriate queues.

    CRITICAL (11 DEC 2025 - No Legacy Fallbacks):
    ALL task types MUST be explicitly listed here. If a task type is not
    in RASTER_TASKS, VECTOR_TASKS, or LONG_RUNNING_TASKS,
    CoreMachine will raise ContractViolationError.
    This prevents silent misrouting and enforces explicit queue assignment.

    Queue Selection Guidelines:
    - RASTER_TASKS: Memory-intensive GDAL operations (2-8GB RAM, low concurrency)
    - VECTOR_TASKS: DB-bound or lightweight operations (high concurrency)
    - LONG_RUNNING_TASKS: Docker worker for large files (no timeout constraints)
    """

    # Long-running tasks → long-running-tasks queue (13 DEC 2025, renamed 22 DEC 2025)
    # Placeholder for Docker worker. When Docker support is added, large
    # tasks will route here instead of raising NotImplementedError.
    # Currently empty - no tasks route here yet.
    LONG_RUNNING_TASKS = [
        # Future: "create_cog_large", "extract_tiles_large", etc.
        # When a job contains files > size threshold, tasks route here
    ]

    # Raster tasks → raster-tasks queue (memory-intensive, low concurrency)
    # ORPHANED ENTRIES REMOVED 29 DEC 2025: handler_raster_*, handler_stac_* prefixed
    # entries did not exist in ALL_HANDLERS - they were never implemented.
    # Raster handlers renamed (29 DEC 2025)
    RASTER_TASKS = [
        # Raster validation and COG creation
        "raster_validate",
        "raster_create_cog",
        "raster_extract_stac_metadata",
        # STAC raster catalog
        "raster_list_files",
        # Tiling and extraction
        "raster_generate_tiling_scheme",
        "raster_extract_tiles",
        # MosaicJSON and STAC collection
        "raster_create_mosaicjson",
        "raster_create_stac_collection",
        # Fathom ETL (memory-intensive raster operations)
        # NOTE: Inventory handlers moved to VECTOR_TASKS (database queries)
        "fathom_band_stack",     # Actual raster: Stack 8 return periods
        "fathom_spatial_merge",  # Actual raster: Merge tiles band-by-band
        # H3 Aggregation (memory-intensive rasterstats operations) - 22 DEC 2025
        "h3_raster_zonal_stats",  # Stage 2: Compute zonal stats (GDAL + rasterstats)
    ]

    # Vector tasks → vector-tasks queue (high concurrency, DB-bound or lightweight)
    # ORPHANED ENTRIES REMOVED 29 DEC 2025: handler_vector_*, handler_stac_* prefixed
    # entries did not exist in ALL_HANDLERS - they were never implemented.
    VECTOR_TASKS = [
        # Vector ETL (idempotent)
        "process_vector_prepare",
        "process_vector_upload",
        "vector_create_stac",
        "vector_extract_stac_metadata",
        # H3 handlers (DB-bound PostGIS operations), renamed (29 DEC 2025)
        "h3_level4_generate",
        "h3_base_generate",
        "h3_insert_to_postgis",
        "h3_create_stac",
        "h3_native_streaming_postgis",
        "h3_generate_grid",
        "h3_cascade_descendants",
        "h3_finalize_pyramid",
        # H3 Aggregation handlers (DB-bound) - 22 DEC 2025
        "h3_inventory_cells",       # Stage 1: Count cells, calculate batches
        "h3_aggregation_finalize",  # Stage 3: Update registry, verify counts
        # Container inventory (lightweight blob listing), renamed (29 DEC 2025)
        "inventory_container_summary",
        "inventory_list_blobs",
        "inventory_analyze_blob",
        "inventory_aggregate_analysis",
        "inventory_classify_geospatial",
        "inventory_aggregate_geospatial",
        # Fathom container inventory (lightweight)
        "fathom_generate_scan_prefixes",
        "fathom_scan_prefix",
        "fathom_assign_grid_cells",
        "fathom_inventory_summary",
        # Fathom ETL inventory handlers (database queries, not raster ops)
        "fathom_tile_inventory",   # Phase 1: Query DB for unprocessed tiles
        "fathom_grid_inventory",   # Phase 2: Query DB for Phase 1 completed
        "fathom_stac_register",    # Shared: Create STAC items (DB + HTTP)
        # Hello world and test handlers (lightweight)
        "hello_world_greeting",
        "hello_world_reply",
        # Unpublish handlers - surgical data removal (12 DEC 2025), renamed (29 DEC 2025)
        # All unpublish tasks are lightweight (STAC queries, blob deletes, DROP TABLE)
        "unpublish_inventory_raster",
        "unpublish_inventory_vector",
        "unpublish_delete_blob",
        "unpublish_drop_table",
        "unpublish_delete_stac",
        # Curated dataset update handlers (15 DEC 2025)
        # Lightweight: HTTP calls, DB operations, file downloads
        "curated_check_source",
        "curated_fetch_data",
        "curated_etl_process",
        "curated_finalize",
        # NOTE: h3_inventory_cells, h3_aggregation_finalize already listed above (lines 298-299)
        # NOTE: h3_raster_zonal_stats is in RASTER_TASKS (memory-intensive rasterstats)
        # STAC Repair handlers (22 DEC 2025)
        # Lightweight: pgSTAC queries, item updates
        "stac_repair_inventory",
        "stac_repair_item",
        # H3 Export handlers (28 DEC 2025)
        # DB-bound: table creation, pgSTAC queries
        "h3_export_validate",
        "h3_export_build",
        "h3_export_register",
        # Ingest Collection handlers (29 DEC 2025)
        # Lightweight: blob copy, pgSTAC operations
        "ingest_inventory",
        "ingest_copy_batch",
        "ingest_register_collection",
        "ingest_register_items",
        "ingest_finalize",
    ]


# =============================================================================
# RASTER DEFAULTS (COG processing)
# =============================================================================

class RasterDefaults:
    """
    Raster processing pipeline defaults.

    Controls COG creation, validation, and MosaicJSON generation.

    Environment Variable Naming Convention (23 DEC 2025):
        RASTER_ROUTE_*  - Orchestration layer (routing decisions)
        RASTER_*        - Handler layer (processing decisions)

    Routing Thresholds (orchestration - decides which pipeline/queue):
        - RASTER_ROUTE_LARGE_MB: Route to process_large_raster_v2 (tiling pipeline)
        - RASTER_ROUTE_DOCKER_MB: Route to Docker worker queue (long-running)
        - RASTER_ROUTE_REJECT_MB: Hard reject - file too large for any pipeline

    Handler Settings (processing - how to process the file):
        - RASTER_COG_IN_MEMORY: rio-cogeo in_memory parameter (False = use /tmp)
        - RASTER_TILE_TARGET_MB: Target uncompressed tile size for extract_tiles

    Memory Estimation Multipliers (dtype-aware, 23 DEC 2025):
        - uint8/int8:   2.5x uncompressed size
        - uint16/int16: 3.0x (upcast during processing)
        - float32:      4.0x (float math + intermediate arrays)
        - float64:      5.0x (double precision overhead)
    """

    # ==========================================================================
    # ORCHESTRATION LAYER - Routing decisions (which pipeline/queue)
    # ==========================================================================

    # Route to large raster pipeline (process_large_raster_v2 with tiling)
    RASTER_ROUTE_LARGE_MB = 1200  # 1.2 GB - files above this use tiling pipeline

    # Route to Docker worker queue (long-running-tasks)
    # Files above this threshold route to Docker regardless of pipeline
    RASTER_ROUTE_DOCKER_MB = 2000  # 2 GB - Docker worker for memory-intensive ops

    # Hard reject - file exceeds maximum supported size
    RASTER_ROUTE_REJECT_MB = 8000  # 8 GB - reject at preflight validation

    # Collection size limit (max files per collection submission)
    RASTER_COLLECTION_MAX_FILES = 20

    # ==========================================================================
    # HANDLER LAYER - Processing decisions (how to process)
    # ==========================================================================

    # Target tile size for extract_tiles (uncompressed MB per tile)
    # Tiles are sized so Function App workers can COG them without OOM
    RASTER_TILE_TARGET_MB = 400  # ~400 MB uncompressed tiles

    # COG creation settings
    COG_COMPRESSION = "deflate"
    COG_JPEG_QUALITY = 85
    COG_TILE_SIZE = 512
    COG_IN_MEMORY = False  # Disk-based (/tmp) - safer with concurrency

    # ==========================================================================
    # MEMORY ESTIMATION - Dtype-aware peak multipliers (23 DEC 2025)
    # ==========================================================================
    # These multipliers estimate peak RAM usage during COG creation
    # based on empirical OOM observations. float32 requires significantly
    # more working memory than int types due to intermediate arrays.

    MEMORY_MULTIPLIER_UINT8 = 2.5   # Simple byte operations
    MEMORY_MULTIPLIER_INT16 = 3.0   # Upcast during processing
    MEMORY_MULTIPLIER_INT32 = 3.5   # Larger intermediates
    MEMORY_MULTIPLIER_FLOAT32 = 4.0 # Float math + intermediate arrays
    MEMORY_MULTIPLIER_FLOAT64 = 5.0 # Double precision overhead

    # Reprojection and validation
    TARGET_CRS = "EPSG:4326"
    OVERVIEW_RESAMPLING = "average"
    REPROJECT_RESAMPLING = "bilinear"
    STRICT_VALIDATION = True

    # MosaicJSON
    MOSAICJSON_MAXZOOM = 19

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

    PICKLE_CONTAINER = "pickles"  # Silver zone - intermediate vector processing
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

    IMPORTANT (23 DEC 2025): Admin0 table lookup REQUIRES a promoted dataset
    with system_role='admin0_boundaries'. There is NO FALLBACK.

    To configure admin0:
        1. Create table via process_vector job
        2. Promote with: POST /api/promote {is_system_reserved: true, system_role: 'admin0_boundaries'}
    """

    # System role for admin0 lookup (REQUIRED - no fallback)
    ADMIN0_SYSTEM_ROLE = "admin0_boundaries"

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
# FATHOM ETL DEFAULTS
# =============================================================================

class FathomDefaults:
    """
    Fathom flood hazard ETL pipeline defaults.

    Controls containers, prefixes, and STAC collection IDs for the
    two-phase Fathom processing architecture.

    Phase 1: Band stacking (8M → 1M files, 8× reduction)
    Phase 2: Spatial merge (1M → 40K files with 5×5 grid)
    """

    # Source data (Fathom Global Flood Maps v3)
    SOURCE_CONTAINER = "bronze-fathom"

    # Phase 1 outputs (band-stacked 1×1 tiles)
    PHASE1_OUTPUT_CONTAINER = "silver-fathom"
    PHASE1_OUTPUT_PREFIX = "fathom-stacked"
    PHASE1_COLLECTION_ID = "fathom-flood-stacked"

    # Phase 2 outputs (spatially merged NxN tiles)
    PHASE2_OUTPUT_CONTAINER = "silver-fathom"
    PHASE2_OUTPUT_PREFIX = "fathom"
    PHASE2_COLLECTION_ID = "fathom-flood"

    # Merge configuration
    DEFAULT_GRID_SIZE = 5  # 5×5 degree grid cells

    # Return periods (bands in output COGs)
    RETURN_PERIODS = ["1in5", "1in10", "1in20", "1in50", "1in100", "1in200", "1in500", "1in1000"]

    # Flood types supported
    FLOOD_TYPES = ["COASTAL_DEFENDED", "COASTAL_UNDEFENDED", "FLUVIAL_DEFENDED", "FLUVIAL_UNDEFENDED", "PLUVIAL_DEFENDED"]


# =============================================================================
# STAC DEFAULTS (Catalog configuration)
# =============================================================================

class STACDefaults:
    """
    STAC catalog configuration defaults.

    Controls collection IDs, metadata, media types, and tier descriptions
    for the pgstac-based STAC catalog system.

    All STAC-related hardcoded values should live here.
    """

    # ==========================================================================
    # LICENSE
    # ==========================================================================
    DEFAULT_LICENSE = "proprietary"

    # ==========================================================================
    # DEFAULT COLLECTION IDs BY DATA TYPE
    # ==========================================================================
    VECTOR_COLLECTION = "system-vectors"      # PostGIS vector tables
    RASTER_COLLECTION = "system-rasters"      # COG files
    H3_COLLECTION = "system-h3-grids"         # H3 hexagonal grids
    DEV_COLLECTION = "dev"                    # Development/testing
    COGS_COLLECTION = "cogs"                  # User-submitted COGs
    VECTORS_COLLECTION = "vectors"            # User-submitted vectors
    GEOPARQUET_COLLECTION = "geoparquet"      # GeoParquet exports

    # ==========================================================================
    # VALID COLLECTIONS (for job parameter validation)
    # ==========================================================================
    VALID_USER_COLLECTIONS = ["dev", "cogs", "vectors", "geoparquet"]
    SYSTEM_COLLECTIONS = ["system-vectors", "system-rasters", "system-h3-grids"]

    # ==========================================================================
    # MEDIA TYPES
    # ==========================================================================
    MEDIA_TYPE_COG = "image/tiff; application=geotiff; profile=cloud-optimized"
    MEDIA_TYPE_GEOTIFF = "image/tiff; application=geotiff"
    MEDIA_TYPE_GEOJSON = "application/geo+json"
    MEDIA_TYPE_GEOPARQUET = "application/x-parquet"
    MEDIA_TYPE_GENERIC = "application/octet-stream"

    # ==========================================================================
    # ASSET TYPES
    # ==========================================================================
    ASSET_TYPE_RASTER = "raster"
    ASSET_TYPE_VECTOR = "vector"
    ASSET_TYPE_MIXED = "mixed"

    # ==========================================================================
    # TIER DESCRIPTIONS
    # ==========================================================================
    TIER_DESCRIPTIONS = {
        "bronze": "Raw geospatial data from Azure Storage container",
        "silver": "Cloud-optimized GeoTIFFs (COGs) with validated metadata and PostGIS integration",
        "gold": "GeoParquet exports optimized for analytical queries",
    }

    # ==========================================================================
    # COLLECTION METADATA (titles and descriptions)
    # ==========================================================================
    COLLECTION_METADATA = {
        "system-vectors": {
            "title": "System STAC - Vector Tables",
            "description": "Operational tracking of PostGIS vector tables created by ETL",
            "asset_type": "vector",
            "media_type": "application/geo+json",
        },
        "system-rasters": {
            "title": "System STAC - Raster Files",
            "description": "Operational tracking of COG files created by ETL",
            "asset_type": "raster",
            "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
        },
        "cogs": {
            "title": "Cloud-Optimized GeoTIFFs",
            "description": "Raster data converted to COG format in EPSG:4326 for cloud-native access",
            "asset_type": "raster",
            "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
        },
        "vectors": {
            "title": "Vector Features (PostGIS)",
            "description": "Vector data stored in PostGIS tables, queryable via OGC API - Features",
            "asset_type": "vector",
            "media_type": "application/geo+json",
        },
        "geoparquet": {
            "title": "GeoParquet Analytical Datasets",
            "description": "Cloud-optimized columnar vector data for analytical queries",
            "asset_type": "vector",
            "media_type": "application/x-parquet",
        },
        "dev": {
            "title": "Development & Testing",
            "description": "Generic collection for development and testing (not for production)",
            "asset_type": "mixed",
            "media_type": "application/octet-stream",
        },
        "system-h3-grids": {
            "title": "H3 Hexagonal Grids",
            "description": "Pre-computed H3 spatial index grids for analytical queries",
            "asset_type": "vector",
            "media_type": "application/geo+json",
        },
    }


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
    VSI_TEST_CONTAINER = "bronze-rasters"  # Default bronze container for VSI health check

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
    "AppModeDefaults",
    "TaskRoutingDefaults",
    "RasterDefaults",
    "VectorDefaults",
    "AnalyticsDefaults",
    "H3Defaults",
    "PlatformDefaults",
    "FathomDefaults",
    "STACDefaults",
    "AppDefaults",
    "KeyVaultDefaults",
]
