# ============================================================================
# CONFIGURATION DEFAULTS
# ============================================================================
# STATUS: Configuration - Single source of truth for all default values
# PURPOSE: Define fail-fast placeholder defaults for Azure resource configuration
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Check 8 Applied - Full operational deployment guide
# ============================================================================

"""
Configuration Defaults - Single source of truth for all default values.

================================================================================
CORPORATE QA/PROD DEPLOYMENT GUIDE
================================================================================

This file defines ALL environment variables required for deployment. Before
deploying to QA or PROD, file service requests to create the Azure resources
listed below, then configure the corresponding environment variables.

FAIL-FAST DESIGN:
    Tenant-specific defaults use INTENTIONALLY INVALID placeholder values
    (e.g., "your-managed-identity-name"). If you see these in error messages,
    the corresponding environment variable was not set.

--------------------------------------------------------------------------------
REQUIRED AZURE RESOURCES (Service Requests Needed)
--------------------------------------------------------------------------------

1. POSTGRESQL FLEXIBLE SERVER
   Service Request: "Create Azure Database for PostgreSQL Flexible Server"
   - SKU: Standard_D4s_v3 or higher for production
   - Enable AAD authentication
   - Create schemas: app, geo, pgstac, h3

   Environment Variables:
     POSTGIS_HOST          = {server-name}.postgres.database.azure.com
     POSTGIS_DATABASE      = {database-name}
     POSTGIS_SCHEMA        = geo
     APP_SCHEMA            = app
     PGSTAC_SCHEMA         = pgstac
     H3_SCHEMA             = h3

2. USER-ASSIGNED MANAGED IDENTITY (Database Admin)
   Service Request: "Create User-Assigned Managed Identity for PostgreSQL"
   - Name: {app-name}-db-admin
   - Role: Azure AD Authentication Administrator on PostgreSQL server
   - Assign to: Function App, TiTiler Web App

   Environment Variable:
     DB_ADMIN_MANAGED_IDENTITY_NAME = {identity-name}

3. STORAGE ACCOUNTS (Trust Zones)
   Service Request: "Create Storage Accounts for geospatial data tiers"
   - Bronze: Raw uploads (blob, private access)
   - Silver: Processed COGs (blob, SAS for TiTiler)
   - Gold: Analytics exports (optional)

   Environment Variables:
     BRONZE_STORAGE_ACCOUNT = {bronze-account-name}
     SILVER_STORAGE_ACCOUNT = {silver-account-name}
     GOLD_STORAGE_ACCOUNT   = {gold-account-name}  # Optional

4. SERVICE BUS NAMESPACE
   Service Request: "Create Azure Service Bus Namespace"
   - SKU: Standard or Premium
   - Create queues: geospatial-jobs, raster-tasks, vector-tasks

   Environment Variables:
     SERVICE_BUS_FQDN              = {namespace}.servicebus.windows.net  # Full FQDN required
     SERVICE_BUS_CONNECTION_STRING = {connection-string}  # Or use managed identity

5. FUNCTION APPS
   Service Request: "Create Azure Function Apps"
   - ETL App: Job orchestration, admin endpoints, web interfaces
   - OGC/STAC App: Public API endpoints (optional, can be same as ETL)

   Environment Variables:
     ETL_APP_URL      = https://{etl-app-name}.azurewebsites.net
     APP_NAME         = {etl-app-name}

6. TITILER WEB APP
   Service Request: "Create Azure Web App for TiTiler tile server"
   - Container: ghcr.io/stac-utils/titiler-pgstac
   - Requires: PostgreSQL access, blob storage SAS

   Environment Variable:
     TITILER_BASE_URL = https://{titiler-app-name}.azurewebsites.net

--------------------------------------------------------------------------------
DEPLOYMENT VERIFICATION
--------------------------------------------------------------------------------

After setting all environment variables, verify with:

    curl https://{app-url}/api/health

Expected response includes:
    "database": {"status": "healthy"}
    "service_bus": {"status": "healthy"}
    "storage": {"status": "healthy"}

Common Failure Messages:
    STARTUP_FAILED: POSTGIS_HOST not configured
    STARTUP_FAILED: DB_ADMIN_MANAGED_IDENTITY_NAME not configured
    Connection refused: PostgreSQL server not accessible (check VNet/firewall)

--------------------------------------------------------------------------------
ORGANIZATION
--------------------------------------------------------------------------------

Classes in this file:
    - AzureDefaults: MUST override - invalid placeholders (fail-fast)
    - StorageDefaults: Container names (universal), account names (must override)
    - DatabaseDefaults: Reference values for schema names
    - QueueDefaults: Service Bus queue names
    - AppModeDefaults: Multi-Function App deployment modes
    - TaskRoutingDefaults: Task type to queue mapping
    - RasterDefaults: COG processing settings
    - VectorDefaults: PostGIS ETL settings
    - AnalyticsDefaults: DuckDB settings
    - H3Defaults: Spatial indexing settings
    - PlatformDefaults: DDH integration settings
    - FathomDefaults: Flood data ETL settings
    - STACDefaults: Catalog configuration
    - AppDefaults: Application-wide settings
    - KeyVaultDefaults: Key Vault integration (future)

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
    Azure resource defaults that MUST be overridden for deployment.

    ============================================================================
    FAIL-FAST DESIGN
    ============================================================================
    These defaults are INTENTIONALLY INVALID placeholder values. If you see
    error messages containing "your-managed-identity-name" or similar, the
    corresponding environment variable was not configured.

    ============================================================================
    SERVICE REQUESTS REQUIRED
    ============================================================================

    1. MANAGED IDENTITY
       ----------------
       Environment Variable: DB_ADMIN_MANAGED_IDENTITY_NAME

       Service Request Template:
           "Create User-Assigned Managed Identity:
            - Name: {app-name}-db-admin
            - Resource Group: {your-resource-group}

            Role Assignments:
            - 'Azure Database for PostgreSQL Flexible Server AAD Administrator'
              Scope: PostgreSQL server resource

            Assign Identity To:
            - Function App: {etl-app-name}
            - Function App: {ogc-stac-app-name} (if separate)
            - Web App: {titiler-app-name}"

       Verification:
           curl https://{app-url}/api/health
           # database.status should be "healthy"

    2. TITILER WEB APP
       ----------------
       Environment Variable: TITILER_BASE_URL

       Service Request Template:
           "Create Azure Web App for Container:
            - Name: {titiler-app-name}
            - Container: ghcr.io/stac-utils/titiler-pgstac:latest
            - App Settings:
              - POSTGRES_HOST={server}.postgres.database.azure.com
              - POSTGRES_DBNAME={database}
              - AZURE_STORAGE_ACCOUNT={silver-account}
            - Managed Identity: Assign {app-name}-db-admin"

       Verification:
           curl https://{titiler-url}/health

    3. FUNCTION APPS
       --------------
       Environment Variables: ETL_APP_URL

       Service Request Template:
           "Create Azure Function App (Python 3.11):
            - Name: {app-name}
            - Plan: B3 Basic or higher (30min timeout needed)
            - Managed Identity: Assign {app-name}-db-admin
            - App Settings: See deployment checklist"

    4. RESOURCE GROUP
       ---------------
       Environment Variable: ADF_RESOURCE_GROUP (for Data Factory operations)

       Note: Usually already exists. Only needed if using Azure Data Factory
       for large file transfers.
    """

    # Managed Identity (Admin) - Override: DB_ADMIN_MANAGED_IDENTITY_NAME
    # Single identity used for ALL database operations (ETL, OGC/STAC, TiTiler)
    # Simplifies architecture - no separate reader identity needed
    MANAGED_IDENTITY_NAME = "your-managed-identity-name"

    # TiTiler tile server - Override: TITILER_BASE_URL
    # TiPG (OGC Features for vectors) runs at {TITILER_BASE_URL}/vector
    TITILER_BASE_URL = "https://your-titiler-webapp-url"

    # ETL/Admin Function App - Override: ETL_APP_URL
    ETL_APP_URL = "https://your-etl-app-url"

    # Azure Resource Group - Override: ADF_RESOURCE_GROUP
    RESOURCE_GROUP = "your-resource-group-name"


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

    V0.8 Queue Architecture (24 JAN 2026):
    - geospatial-jobs: Job orchestration (Platform/Orchestrator apps listen)
    - container-tasks: Docker worker (ALL heavy operations - GDAL, geopandas, bulk SQL)
    - functionapp-tasks: FunctionApp worker (lightweight DB ops, inventory)

    All task types MUST be explicitly mapped in TaskRoutingDefaults.
    Unmapped task types will raise ContractViolationError (no fallback).
    """

    JOBS_QUEUE = "geospatial-jobs"

    # V0.8: New consolidated queues (24 JAN 2026)
    CONTAINER_TASKS_QUEUE = "container-tasks"      # Docker worker (heavy ops)
    FUNCTIONAPP_TASKS_QUEUE = "functionapp-tasks"  # FunctionApp worker (lightweight)

    # DEPRECATED: Keep for migration period (remove after V0.8 stabilizes)
    RASTER_TASKS_QUEUE = "raster-tasks"            # DEPRECATED → use FUNCTIONAPP_TASKS_QUEUE
    VECTOR_TASKS_QUEUE = "vector-tasks"            # DEPRECATED → use FUNCTIONAPP_TASKS_QUEUE
    LONG_RUNNING_TASKS_QUEUE = "long-running-tasks"  # DEPRECATED → use CONTAINER_TASKS_QUEUE

    # Service outage alerts queue (22 JAN 2026)
    # External service health monitoring sends outage/recovery notifications here
    SERVICE_OUTAGE_ALERTS_QUEUE = "service-outage-alerts"

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

    V0.8 Architecture (24 JAN 2026):
    - 5 clean modes for 3 deployment configurations
    - Centralized orchestration: Orchestrator handles jobs queue
    - Distributed execution: Workers process task queues
    - Docker workers: Heavy operations without Azure Functions timeout constraints

    Mode Summary:
    - standalone: All queues, all HTTP (development only)
    - platform: HTTP gateway only, sends to jobs queue (external entry point)
    - orchestrator: Jobs queue + all HTTP (can combine with platform)
    - worker_functionapp: functionapp-tasks queue (lightweight ops)
    - worker_docker: container-tasks queue (heavy ops)
    """

    # V0.8: 5 clean modes (25 JAN 2026)
    STANDALONE = "standalone"                 # All queues, all endpoints (dev)
    PLATFORM = "platform"                     # HTTP only, sends to jobs queue
    ORCHESTRATOR = "orchestrator"             # Jobs queue + all HTTP
    WORKER_FUNCTIONAPP = "worker_functionapp" # functionapp-tasks queue
    WORKER_DOCKER = "worker_docker"           # container-tasks queue (Docker)

    VALID_MODES = [
        STANDALONE, PLATFORM, ORCHESTRATOR, WORKER_FUNCTIONAPP, WORKER_DOCKER
    ]

    DEFAULT_MODE = STANDALONE
    # App name used for task tracking (INTENTIONALLY INVALID - set APP_NAME env var)
    DEFAULT_APP_NAME = "your-function-app-name"

    # Docker worker integration (08 JAN 2026)
    # When False, standalone mode skips container-tasks queue validation
    # Set to True when a Docker worker is deployed and processing container-tasks
    DOCKER_WORKER_ENABLED = False


# =============================================================================
# TASK ROUTING DEFAULTS (Task Type → Queue Mapping)
# =============================================================================

class TaskRoutingDefaults:
    """
    Task type to queue category mapping.

    Maps task_type → routing category (docker, functionapp).
    CoreMachine uses this to route tasks to appropriate queues.

    V0.8 Architecture (24 JAN 2026):
    ALL task types MUST be explicitly listed in DOCKER_TASKS or FUNCTIONAPP_TASKS.
    Unmapped task types raise ContractViolationError (no fallback).

    Queue Selection Guidelines:
    - DOCKER_TASKS → container-tasks: GDAL, geopandas, bulk SQL (heavy ops)
    - FUNCTIONAPP_TASKS → functionapp-tasks: DB queries, inventory, STAC ops
    """

    # =========================================================================
    # DOCKER_TASKS → container-tasks queue (V0.8 - 24 JAN 2026)
    # =========================================================================
    # All GDAL, geopandas, and heavy pgstac SQL operations.
    # Docker worker tasks - no Azure Functions timeout constraints.
    DOCKER_TASKS = frozenset([
        # =====================================================================
        # CONSOLIDATED RASTER HANDLERS (Docker-only)
        # =====================================================================
        "raster_process_complete",        # F7.13: Validate → COG → STAC
        "raster_process_large_complete",  # F7.18: Tiling pipeline (deprecated)
        "raster_collection_complete",     # V0.8: Collection to COGs (sequential)

        # =====================================================================
        # H3 PYRAMID (Docker-only)
        # =====================================================================
        "h3_pyramid_complete",            # F7.20: H3 pyramid (post-V0.8)

        # =====================================================================
        # RASTER OPERATIONS (GDAL-dependent)
        # =====================================================================
        "raster_validate",
        "raster_create_cog",
        "raster_extract_stac_metadata",
        "raster_list_files",
        "raster_generate_tiling_scheme",
        "raster_extract_tiles",
        "raster_create_mosaicjson",
        "raster_create_stac_collection",

        # =====================================================================
        # FATHOM RASTER OPERATIONS (GDAL)
        # =====================================================================
        "fathom_band_stack",              # Stack 8 return periods
        "fathom_spatial_merge",           # Merge tiles band-by-band
        "fathom_process_chunk",           # V0.8: Band stack + VRT merge + STAC

        # =====================================================================
        # H3 RASTER AGGREGATION (rasterstats - memory intensive)
        # =====================================================================
        "h3_raster_zonal_stats",          # Compute zonal stats (GDAL + rasterstats)

        # =====================================================================
        # VECTOR ETL - DOCKER (V0.8 - geopandas + connection pooling)
        # =====================================================================
        "vector_docker_complete",         # V0.8: Consolidated vector ETL with checkpoints
    ])

    # =========================================================================
    # FUNCTIONAPP_TASKS → functionapp-tasks queue (V0.8 - 24 JAN 2026)
    # =========================================================================
    # Lightweight DB operations, inventory, STAC queries.
    # Runs on FunctionApp worker (with timeout constraints).
    FUNCTIONAPP_TASKS = frozenset([
        # =====================================================================
        # LEGACY VECTOR ETL (FunctionApp - backup/admin only after V0.8)
        # =====================================================================
        "process_vector_prepare",
        "process_vector_upload",
        "vector_create_stac",
        "vector_extract_stac_metadata",

        # =====================================================================
        # INVENTORY OPERATIONS (blob listing, lightweight)
        # =====================================================================
        "inventory_container_summary",
        "inventory_list_blobs",
        "inventory_analyze_blob",
        "inventory_aggregate_analysis",
        "inventory_classify_geospatial",
        "inventory_aggregate_geospatial",

        # =====================================================================
        # FATHOM INVENTORY (DB queries, not raster)
        # =====================================================================
        "fathom_generate_scan_prefixes",
        "fathom_scan_prefix",
        "fathom_assign_grid_cells",
        "fathom_inventory_summary",
        "fathom_tile_inventory",
        "fathom_grid_inventory",
        "fathom_stac_register",
        "fathom_stac_rebuild",
        "fathom_chunk_inventory",
        "fathom_finalize",

        # =====================================================================
        # H3 POSTGIS OPERATIONS (DB-bound, not memory intensive)
        # =====================================================================
        "h3_create_stac",
        "h3_native_streaming_postgis",
        "h3_generate_grid",
        "h3_cascade_descendants",
        "h3_finalize_pyramid",
        "h3_inventory_cells",
        "h3_aggregation_finalize",

        # =====================================================================
        # STAC OPERATIONS (pgSTAC queries, lightweight)
        # =====================================================================
        "stac_repair_inventory",
        "stac_repair_item",
        "stac_rebuild_validate",
        "stac_rebuild_item",

        # =====================================================================
        # UNPUBLISH OPERATIONS (STAC queries, blob deletes)
        # =====================================================================
        "unpublish_inventory_raster",
        "unpublish_inventory_vector",
        "unpublish_delete_blob",
        "unpublish_drop_table",
        "unpublish_delete_stac",

        # =====================================================================
        # CURATED DATASET UPDATES (HTTP, DB, lightweight)
        # =====================================================================
        "curated_check_source",
        "curated_fetch_data",
        "curated_etl_process",
        "curated_finalize",

        # =====================================================================
        # H3 EXPORT (DB-bound)
        # =====================================================================
        "h3_export_validate",
        "h3_export_build",
        "h3_export_register",

        # =====================================================================
        # INGEST COLLECTION (blob copy, pgSTAC)
        # =====================================================================
        "ingest_inventory",
        "ingest_copy_batch",
        "ingest_register_collection",
        "ingest_register_items",
        "ingest_finalize",

        # =====================================================================
        # ORPHAN BLOB OPERATIONS (blob listing, DB queries)
        # =====================================================================
        "orphan_blob_inventory",
        "silver_blob_validate",
        "silver_blob_register",

        # =====================================================================
        # TEST HANDLERS
        # =====================================================================
        "hello_world_greeting",
        "hello_world_reply",
    ])

    # =========================================================================
    # DEPRECATED: Keep for backward compatibility during migration
    # =========================================================================
    # These are aliases pointing to the same tasks for migration period
    LONG_RUNNING_TASKS = list(DOCKER_TASKS)  # DEPRECATED → use DOCKER_TASKS
    RASTER_TASKS = []  # DEPRECATED → merged into DOCKER_TASKS
    VECTOR_TASKS = []  # DEPRECATED → merged into FUNCTIONAPP_TASKS


# =============================================================================
# RASTER DEFAULTS (COG processing)
# =============================================================================

class RasterDefaults:
    """
    Raster processing pipeline defaults.

    Controls COG creation, validation, and MosaicJSON generation.

    V0.8 Architecture (24 JAN 2026):
        - ALL raster operations run on Docker worker
        - ETL mount (Azure Files) is REQUIRED for production
        - Single workflow (process_raster_docker) handles both single COG and tiled output
        - Tiling decision is internal based on RASTER_TILING_THRESHOLD_MB

    Key Settings:
        - USE_ETL_MOUNT: Expected True in production (False = degraded state)
        - RASTER_TILING_THRESHOLD_MB: When to produce tiled output vs single COG
        - RASTER_TILE_TARGET_MB: Target size per tile when tiling

    Memory Estimation Multipliers (dtype-aware, 23 DEC 2025):
        - uint8/int8:   2.5x uncompressed size
        - uint16/int16: 3.0x (upcast during processing)
        - float32:      4.0x (float math + intermediate arrays)
        - float64:      5.0x (double precision overhead)
    """

    # ==========================================================================
    # V0.8 ETL MOUNT SETTINGS (24 JAN 2026)
    # ==========================================================================
    # Docker workers use Azure Files mount for GDAL temp files.
    # This allows processing files larger than container RAM without OOM.
    #
    # Mount path: /mounts/etl-temp (configured via Azure Portal)
    # GDAL uses this via CPL_TMPDIR environment variable.

    USE_ETL_MOUNT = True  # V0.8: Mount is expected (False = degraded state)
    ETL_MOUNT_PATH = "/mounts/etl-temp"  # Mount path in Docker container

    # ==========================================================================
    # TILING SETTINGS (V0.8 - 24 JAN 2026)
    # ==========================================================================
    # Single workflow (process_raster_docker) decides internally:
    #   - File ≤ threshold → Single COG output
    #   - File > threshold → N COG tiles (tiled output)

    RASTER_TILING_THRESHOLD_MB = 2000  # 2GB - files above this produce tiled output
    RASTER_TILE_TARGET_MB = 400  # ~400 MB per tile when tiling

    # Collection size limit (max files per collection submission)
    RASTER_COLLECTION_MAX_FILES = 20

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
    Phase 2: Spatial merge (1M → 60K files with 4×4 grid)

    V0.8 Architecture (24 JAN 2026):
        - 3-stage hybrid job: Functions (inventory/finalize) + Docker (processing)
        - VRT-based merge for memory efficiency (~500MB vs 2-5GB peak)
        - Continent/multi-region parallelism via fan-out to Docker workers
        - Country-based collections: fathom-flood-{region}
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
    # Changed from 5 to 4 (06 JAN 2026): 5×5 grids caused OOM with 24 tiles @ 5-6GB each
    # 4×4 grids = max 16 tiles @ ~3-4GB peak memory, fits in 8GB instance
    DEFAULT_GRID_SIZE = 4  # 4×4 degree grid cells

    # Return periods (bands in output COGs)
    RETURN_PERIODS = ["1in5", "1in10", "1in20", "1in50", "1in100", "1in200", "1in500", "1in1000"]

    # Short band names for STAC metadata
    RETURN_PERIOD_NAMES = ["RP5", "RP10", "RP20", "RP50", "RP75", "RP100", "RP250", "RP500"]

    # Flood types supported
    FLOOD_TYPES = ["COASTAL_DEFENDED", "COASTAL_UNDEFENDED", "FLUVIAL_DEFENDED", "FLUVIAL_UNDEFENDED", "PLUVIAL_DEFENDED"]

    # =========================================================================
    # CONTINENT REGION MAPPINGS (V0.8 - 24 JAN 2026)
    # =========================================================================
    # Maps continent names to lists of ISO3 country codes for fan-out parallelism.
    # Used by process_fathom_docker job to expand continent → regions.

    CONTINENT_REGIONS = {
        'africa': [
            'dza', 'ago', 'ben', 'bwa', 'bfa', 'bdi', 'cmr', 'cpv', 'caf',
            'tcd', 'com', 'cog', 'cod', 'dji', 'egy', 'gnq', 'eri', 'swz',
            'eth', 'gab', 'gmb', 'gha', 'gin', 'gnb', 'civ', 'ken', 'lso',
            'lbr', 'lby', 'mdg', 'mwi', 'mli', 'mrt', 'mus', 'mar', 'moz',
            'nam', 'ner', 'nga', 'rwa', 'stp', 'sen', 'syc', 'sle', 'som',
            'zaf', 'ssd', 'sdn', 'tza', 'tgo', 'tun', 'uga', 'zmb', 'zwe'
        ],
        'asia': [
            'afg', 'arm', 'aze', 'bhr', 'bgd', 'btn', 'brn', 'khm', 'chn',
            'cyp', 'geo', 'ind', 'idn', 'irn', 'irq', 'isr', 'jpn', 'jor',
            'kaz', 'kwt', 'kgz', 'lao', 'lbn', 'mys', 'mdv', 'mng', 'mmr',
            'npl', 'prk', 'omn', 'pak', 'phl', 'qat', 'sau', 'sgp', 'kor',
            'lka', 'syr', 'twn', 'tjk', 'tha', 'tls', 'tur', 'tkm', 'are',
            'uzb', 'vnm', 'yem'
        ],
        'europe': [
            'alb', 'and', 'aut', 'blr', 'bel', 'bih', 'bgr', 'hrv', 'cze',
            'dnk', 'est', 'fin', 'fra', 'deu', 'grc', 'hun', 'isl', 'irl',
            'ita', 'xkx', 'lva', 'lie', 'ltu', 'lux', 'mlt', 'mda', 'mco',
            'mne', 'nld', 'mkd', 'nor', 'pol', 'prt', 'rou', 'rus', 'smr',
            'srb', 'svk', 'svn', 'esp', 'swe', 'che', 'ukr', 'gbr', 'vat'
        ],
        'north_america': [
            'atg', 'bhs', 'brb', 'blz', 'can', 'cri', 'cub', 'dma', 'dom',
            'slv', 'grd', 'gtm', 'hti', 'hnd', 'jam', 'mex', 'nic', 'pan',
            'kna', 'lca', 'vct', 'tto', 'usa'
        ],
        'south_america': [
            'arg', 'bol', 'bra', 'chl', 'col', 'ecu', 'guy', 'pry', 'per',
            'sur', 'ury', 'ven'
        ],
        'oceania': [
            'aus', 'fji', 'kir', 'mhl', 'fsm', 'nru', 'nzl', 'plw', 'png',
            'wsm', 'slb', 'ton', 'tuv', 'vut'
        ]
    }

    # Maximum tiles per chunk before splitting (for adaptive chunking)
    MAX_TILES_PER_CHUNK = 500


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
    # RASTER_COLLECTION removed (14 JAN 2026) - collection_id now required for all raster jobs
    H3_COLLECTION = "system-h3-grids"         # H3 hexagonal grids
    DEV_COLLECTION = "dev"                    # Development/testing
    COGS_COLLECTION = "cogs"                  # User-submitted COGs
    VECTORS_COLLECTION = "vectors"            # User-submitted vectors
    GEOPARQUET_COLLECTION = "geoparquet"      # GeoParquet exports

    # ==========================================================================
    # VALID COLLECTIONS (for job parameter validation)
    # ==========================================================================
    VALID_USER_COLLECTIONS = ["dev", "cogs", "vectors", "geoparquet"]
    SYSTEM_COLLECTIONS = ["system-vectors", "system-h3-grids"]  # system-rasters removed

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
        # system-rasters removed (14 JAN 2026) - collection_id now required for all raster jobs
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
# OBSERVABILITY DEFAULTS (10 JAN 2026 - F7.12.C Flag Consolidation)
# =============================================================================

class ObservabilityDefaults:
    """
    Observability configuration defaults.

    Controls unified debug instrumentation across the application.

    FLAG CONSOLIDATION (10 JAN 2026):
        BEFORE: DEBUG_MODE, DEBUG_LOGGING, METRICS_DEBUG_MODE (confusing)
        AFTER:  OBSERVABILITY_MODE (single unified flag)

    Features controlled by OBSERVABILITY_MODE:
        - Memory/CPU tracking (log_memory_checkpoint)
        - Service latency tracking (@track_latency)
        - Blob metrics logging (MetricsBlobLogger)
        - Database stats collection (get_database_stats)
        - Verbose diagnostics output
    """

    # Master switch for all observability features
    OBSERVABILITY_MODE = False


# =============================================================================
# APPLICATION DEFAULTS
# =============================================================================

class AppDefaults:
    """
    Application-wide defaults.

    Controls debug mode, logging, health checks, and timeouts.

    NOTE (10 JAN 2026): DEBUG_MODE is now an alias for OBSERVABILITY_MODE.
    Prefer using OBSERVABILITY_MODE env var for new deployments.
    DEBUG_MODE is kept for backward compatibility.
    """

    # Environment
    DEBUG_MODE = False  # Legacy - use OBSERVABILITY_MODE instead
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
    "ObservabilityDefaults",
    "AppDefaults",
    "KeyVaultDefaults",
]
