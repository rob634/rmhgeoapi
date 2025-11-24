# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Production-ready configuration with multi-account storage pattern
# NOTE: This is a SERVICE BUS ONLY application - Storage Queues are NOT supported
# PURPOSE: Central configuration management with Pydantic v2 validation for Azure Geospatial ETL Pipeline
# EXPORTS: AppConfig, get_config(), QueueNames, debug_config(), CogTier, CogTierProfile, COG_TIER_PROFILES, determine_applicable_tiers()
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

Centralized configuration using Pydantic v2 for runtime validation, type safety,
and comprehensive documentation of environment variables. Single source of truth
for application configuration.

Key Features:
- Pydantic v2 schema validation with runtime type checking
- Environment variable documentation with examples
- Computed properties for Azure service URLs and connection strings
- Azure naming convention validation
- Factory methods and sanitized debug output

Configuration Categories:
- Azure Storage: Multi-account trust zones (Bronze/Silver/SilverExternal)
- PostgreSQL/PostGIS: Database connection and schema configuration
- Security: Azure Key Vault integration
- Queues: Service Bus and Storage Queue configuration
- Raster/Vector Pipelines: COG tiers, compression, validation
- Application: Timeouts, retry policies, logging

Usage:
    config = get_config()
    blob_url = config.blob_service_url
    debug_info = debug_config()  # Passwords masked
"""
import os
from typing import Optional, List, Literal
from enum import Enum
from pydantic import BaseModel, Field, field_validator, ValidationError


# ============================================================================
# COG TIER CONFIGURATION (19 OCT 2025)
# ============================================================================
# Multi-tier COG architecture for storage/performance trade-offs
# ============================================================================

class CogTier(str, Enum):
    """
    COG output tiers balancing compression, quality, and storage cost.

    Tiers:
        VISUALIZATION: JPEG (lossy), hot storage, web-optimized
            - RGB only (3 bands, uint8) - ~17 MB for 200 MB (90% reduction)

        ANALYSIS: DEFLATE (lossless), hot storage, analysis-ready
            - Universal compatibility - ~50 MB for 200 MB (75% reduction)

        ARCHIVE: LZW (lossless), cool storage, long-term compliance
            - Universal compatibility - ~180 MB for 200 MB (10% reduction)

    Compatibility:
        - RGB (3 bands, uint8): All 3 tiers
        - DEM/multispectral: ANALYSIS + ARCHIVE only (JPEG incompatible)

    Usage:
        from config import determine_applicable_tiers
        tiers = determine_applicable_tiers(band_count=3, data_type='uint8')

    See Also: CogTierProfile, determine_applicable_tiers()
    """
    VISUALIZATION = "visualization"
    ANALYSIS = "analysis"
    ARCHIVE = "archive"


class StorageAccessTier(str, Enum):
    """Azure Blob Storage access tiers."""
    HOT = "hot"
    COOL = "cool"


class CogTierProfile(BaseModel):
    """
    COG tier profile with compression settings and compatibility rules.

    Attributes:
        tier: CogTier enum (VISUALIZATION, ANALYSIS, ARCHIVE)
        compression: Algorithm ("JPEG", "DEFLATE", "LZW")
        quality: JPEG quality (1-100), None for lossless
        predictor: Lossless compression predictor (1=none, 2=horizontal)
        zlevel: DEFLATE compression level (1-9)
        blocksize: Internal tile size in pixels (512)
        storage_tier: Azure storage tier (hot, cool, archive)
        requires_rgb: True if tier only works with RGB (3 bands, uint8)
        supports_float: True if tier supports float32/float64
        supports_multiband: True if tier supports >3 bands

    Methods:
        is_compatible(band_count, data_type): Check raster compatibility

    Compatibility:
        - VISUALIZATION (JPEG): Requires exactly 3 bands + uint8
        - ANALYSIS/ARCHIVE: Universal (all band counts and data types)

    Example:
        profile = COG_TIER_PROFILES[CogTier.VISUALIZATION]
        compatible = profile.is_compatible(3, 'uint8')  # True
        compatible = profile.is_compatible(1, 'float32')  # False
    """
    tier: CogTier
    compression: str  # e.g., "JPEG", "DEFLATE", "LZW"
    quality: Optional[int] = None  # JPEG quality (1-100), None for lossless
    predictor: Optional[int] = 2  # Predictor for lossless compression
    zlevel: Optional[int] = 6  # Compression level for DEFLATE
    blocksize: int = 512  # Internal tile size
    storage_tier: StorageAccessTier  # Azure storage tier
    description: str
    use_case: str

    # Compatibility rules
    requires_rgb: bool = False  # True if tier only works with RGB (3 bands, uint8)
    supports_float: bool = True  # True if tier supports floating point data
    supports_multiband: bool = True  # True if tier supports >3 bands

    def is_compatible(self, band_count: int, data_type: str) -> bool:
        """
        Check if this tier is compatible with raster characteristics.

        Evaluates compatibility based on band count and data type against tier
        requirements. JPEG (visualization) tier has strict requirements, while
        DEFLATE/LZW (analysis/archive) tiers are universally compatible.

        Args:
            band_count: Number of bands in raster (1=DEM, 3=RGB, 4=RGBA, 8=Landsat)
            data_type: Numpy dtype string (e.g., 'uint8', 'uint16', 'float32', 'float64')

        Returns:
            True if tier can be applied to this raster type, False otherwise

        Compatibility Logic:
            1. If tier requires RGB (JPEG visualization):
               - Must have exactly 3 bands AND uint8 data type
               - Returns False for DEM (1 band), Landsat (8 bands), or float data

            2. If tier doesn't support float data (JPEG):
               - Returns False for any float32 or float64 data type
               - Returns True for uint8, uint16, int16, etc.

            3. If tier doesn't support multiband (JPEG):
               - Returns False for band_count > 3 (e.g., Landsat, Sentinel)
               - Returns True for 1-3 bands

            4. Otherwise (DEFLATE, LZW):
               - Returns True (universal compatibility)

        Examples:
            # JPEG visualization tier with RGB
            >>> profile = COG_TIER_PROFILES[CogTier.VISUALIZATION]
            >>> profile.is_compatible(3, 'uint8')
            True

            # JPEG visualization tier with DEM (incompatible)
            >>> profile.is_compatible(1, 'float32')
            False  # JPEG requires RGB (3 bands, uint8)

            # DEFLATE analysis tier with DEM (compatible)
            >>> profile = COG_TIER_PROFILES[CogTier.ANALYSIS]
            >>> profile.is_compatible(1, 'float32')
            True  # DEFLATE is universal

            # JPEG visualization tier with Landsat (incompatible)
            >>> profile = COG_TIER_PROFILES[CogTier.VISUALIZATION]
            >>> profile.is_compatible(8, 'uint16')
            False  # JPEG requires exactly 3 bands

        See Also:
            - determine_applicable_tiers(): Checks all tiers at once
            - services/raster_validation.py: Calls this during Stage 1
            - services/raster_cog.py: Uses result for fallback logic
        """
        # RGB-only tier (JPEG visualization)
        if self.requires_rgb:
            return band_count == 3 and data_type == 'uint8'

        # Check float support
        if 'float' in data_type.lower() and not self.supports_float:
            return False

        # Check multiband support
        if band_count > 3 and not self.supports_multiband:
            return False

        return True


# Predefined COG tier profiles
COG_TIER_PROFILES = {
    CogTier.VISUALIZATION: CogTierProfile(
        tier=CogTier.VISUALIZATION,
        compression="JPEG",
        quality=85,
        predictor=None,
        zlevel=None,
        blocksize=512,
        storage_tier=StorageAccessTier.HOT,
        description="Web-optimized visualization tier with lossy compression",
        use_case="Fast web maps, public viewers, visualization",
        requires_rgb=True,  # JPEG only works with RGB
        supports_float=False,
        supports_multiband=False
    ),
    CogTier.ANALYSIS: CogTierProfile(
        tier=CogTier.ANALYSIS,
        compression="DEFLATE",
        quality=None,  # Lossless
        predictor=2,
        zlevel=6,
        blocksize=512,
        storage_tier=StorageAccessTier.HOT,
        description="Lossless compression for scientific analysis",
        use_case="GIS operations, data analysis, preserves data quality",
        requires_rgb=False,  # Works with all raster types
        supports_float=True,
        supports_multiband=True
    ),
    CogTier.ARCHIVE: CogTierProfile(
        tier=CogTier.ARCHIVE,
        compression="LZW",
        quality=None,  # Lossless
        predictor=2,
        zlevel=None,
        blocksize=512,
        storage_tier=StorageAccessTier.COOL,
        description="Minimal compression for long-term storage",
        use_case="Regulatory compliance, long-term archive, original data preservation",
        requires_rgb=False,  # Works with all raster types
        supports_float=True,
        supports_multiband=True
    )
}


def determine_applicable_tiers(band_count: int, data_type: str) -> List[CogTier]:
    """
    Determine which COG tiers are compatible with raster characteristics.

    Checks each tier's compatibility rules and returns applicable tiers.
    Used during Stage 1 validation before COG creation.

    Args:
        band_count: Number of bands (1=DEM, 3=RGB, 4=RGBA, 8+=multispectral)
        data_type: Numpy dtype ('uint8', 'uint16', 'float32', etc.)

    Returns:
        List of compatible CogTier enums. Always includes ANALYSIS and ARCHIVE
        (universal). Includes VISUALIZATION only for RGB (3 bands, uint8).

    Compatibility Rules:
        - VISUALIZATION (JPEG): Requires 3 bands + uint8
        - ANALYSIS (DEFLATE): Universal (all rasters)
        - ARCHIVE (LZW): Universal (all rasters)

    Examples:
        >>> determine_applicable_tiers(3, 'uint8')  # RGB
        [CogTier.VISUALIZATION, CogTier.ANALYSIS, CogTier.ARCHIVE]

        >>> determine_applicable_tiers(1, 'float32')  # DEM
        [CogTier.ANALYSIS, CogTier.ARCHIVE]

    See Also: CogTier, CogTierProfile.is_compatible()
    """
    applicable = []

    for tier, profile in COG_TIER_PROFILES.items():
        if profile.is_compatible(band_count, data_type):
            applicable.append(tier)

    return applicable


# ============================================================================
# MULTI-ACCOUNT STORAGE CONFIGURATION (29 OCT 2025)
# ============================================================================
# Three-account storage pattern for trust zone separation
# See: MULTI_ACCOUNT_STORAGE_ARCHITECTURE.md
# ============================================================================

class StorageAccountConfig(BaseModel):
    """
    Configuration for a single storage account with purpose-specific containers.

    Design: Currently all three "accounts" use rmhazuregeo, but container
    names are prefixed to simulate separation (bronze-*, silver-*, silverext-*).

    Future: Each account will be a separate Azure Storage Account with
    independent networking, access policies, and lifecycle rules.

    Trust Zones:
        Bronze: Untrusted user uploads (write-only for users, read-only for ETL)
        Silver: Trusted processed data (ETL read-write, REST API read-only)
        SilverExternal: Airgapped replica (ETL push-only, one-way sync)
    """
    account_name: str = Field(
        description="Azure Storage Account name"
    )

    container_prefix: str = Field(
        description="Prefix for containers in this account (e.g., 'bronze', 'silver')"
    )

    # Purpose-specific containers (flat namespace within account)
    vectors: str = Field(description="Vector data container (Shapefiles, GeoJSON, GeoPackage)")
    rasters: str = Field(description="Raster data container (GeoTIFF, raw rasters)")
    cogs: str = Field(description="Cloud Optimized GeoTIFFs (analysis + visualization tiers)")
    tiles: str = Field(description="Raster tiles (temporary or permanent)")
    mosaicjson: str = Field(description="MosaicJSON metadata files")
    stac_assets: str = Field(description="STAC asset files (thumbnails, metadata)")
    misc: str = Field(description="Miscellaneous files (logs, reports)")
    temp: str = Field(description="Temporary processing files (auto-cleanup)")

    # Optional: Connection override (for airgapped external)
    connection_string: Optional[str] = Field(
        default=None,
        description="Override connection string for isolated networks"
    )

    def get_container(self, purpose: str) -> str:
        """
        Get fully qualified container name.

        Args:
            purpose: Data purpose (vectors, rasters, cogs, tiles, etc.)

        Returns:
            Container name with account prefix

        Example:
            bronze_account.get_container("vectors") → "bronze-vectors"
            silver_account.get_container("cogs") → "silver-cogs"

        Raises:
            ValueError: If purpose is unknown
        """
        if not hasattr(self, purpose):
            raise ValueError(
                f"Unknown container purpose: {purpose}. "
                f"Valid options: vectors, rasters, cogs, tiles, mosaicjson, "
                f"stac_assets, misc, temp"
            )
        return getattr(self, purpose)


class MultiAccountStorageConfig(BaseModel):
    """
    Multi-account storage configuration for trust zones.

    Current State (02 NOV 2025):
    - All four "accounts" use rmhazuregeo storage account
    - Containers are prefixed to simulate account separation:
      - bronze-vectors, bronze-rasters (Bronze: raw uploads)
      - silver-cogs, silver-vectors (Silver: processed data)
      - silverext-cogs, silverext-vectors (SilverExternal: airgapped replica)
      - gold-geoparquet, gold-h3-grids (Gold: analytics-ready exports)

    Trust Zone Pattern:
    - Bronze: Untrusted raw data (user uploads)
    - Silver: Trusted processed data (COGs, vectors in PostGIS)
    - SilverExternal: Airgapped secure replica
    - Gold: Analytics-ready exports (GeoParquet, H3 grids, DuckDB-optimized)

    Future State (When Ready for Production):
    - Bronze: Separate storage account (rmhgeo-bronze) in untrusted VNET
    - Silver: Separate storage account (rmhgeo-silver) in trusted VNET
    - SilverExternal: Separate storage account in airgapped VNET
    - Gold: Separate storage account (rmhgeo-gold) for analytics

    Migration Path:
    - Change account_name per tier → zero code changes
    - Container names stay the same (bronze-vectors, gold-geoparquet, etc.)
    """

    # BRONZE: Untrusted raw data zone
    bronze: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv("STORAGE_ACCOUNT_NAME", "rmhazuregeo"),
            container_prefix="bronze",
            vectors="bronze-vectors",
            rasters="bronze-rasters",
            misc="bronze-misc",
            temp="bronze-temp",
            # Not used in Bronze (no processed outputs):
            cogs="bronze-notused",
            tiles="bronze-notused",
            mosaicjson="bronze-notused",
            stac_assets="bronze-notused"
        )
    )

    # SILVER: Trusted processed data + REST API serving
    silver: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv("STORAGE_ACCOUNT_NAME", "rmhazuregeo"),
            container_prefix="silver",
            vectors="silver-vectors",
            rasters="silver-rasters",
            cogs="silver-cogs",
            tiles="silver-tiles",
            mosaicjson="silver-mosaicjson",
            stac_assets="silver-stac-assets",
            misc="silver-misc",
            temp="silver-temp"
        )
    )

    # SILVER EXTERNAL: Airgapped secure environment replica
    silverext: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv("STORAGE_ACCOUNT_NAME", "rmhazuregeo"),
            container_prefix="silverext",
            vectors="silverext-vectors",
            rasters="silverext-rasters",
            cogs="silverext-cogs",
            tiles="silverext-tiles",
            mosaicjson="silverext-mosaicjson",
            stac_assets="silverext-stac-assets",
            misc="silverext-misc",
            temp="silverext-temp",
            # Optional: Connection string for airgapped network
            connection_string=os.getenv("SILVEREXT_CONNECTION_STRING")
        )
    )

    # GOLD: Analytics-ready exports (GeoParquet, H3 grids, DuckDB-optimized)
    gold: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv("STORAGE_ACCOUNT_NAME", "rmhazuregeo"),
            container_prefix="gold",
            vectors="gold-geoparquet",     # GeoParquet vector exports
            rasters="gold-notused",        # Not used (COGs in silver)
            cogs="gold-notused",           # Not used (COGs in silver)
            tiles="gold-notused",          # Not used (tiles in silver)
            mosaicjson="gold-notused",     # Not used (MosaicJSON in silver)
            stac_assets="gold-notused",    # Not used (STAC in silver)
            misc="gold-h3-grids",          # H3 hexagonal grid GeoParquet files
            temp="gold-temp"               # Temporary analytics processing
        )
    )

    def get_account(self, zone: str) -> StorageAccountConfig:
        """
        Get storage account config by trust zone.

        Args:
            zone: Trust zone ("bronze", "silver", "silverext", "gold")

        Returns:
            StorageAccountConfig for that zone

        Example:
            storage.get_account("bronze").get_container("vectors")
            → "bronze-vectors"

            storage.get_account("gold").get_container("misc")
            → "gold-h3-grids"

        Raises:
            ValueError: If zone is unknown
        """
        if zone == "bronze":
            return self.bronze
        elif zone == "silver":
            return self.silver
        elif zone == "silverext":
            return self.silverext
        elif zone == "gold":
            return self.gold
        else:
            raise ValueError(
                f"Unknown storage zone: {zone}. "
                f"Valid options: bronze, silver, silverext, gold"
            )


class AppConfig(BaseModel):
    """
    Strongly typed application configuration using Pydantic v2.

    All environment variables are documented, validated, and typed.
    Provides single source of truth for configuration management.
    """

    # ========================================================================
    # Multi-Account Storage Configuration (NEW - 29 OCT 2025)
    # ========================================================================

    storage: MultiAccountStorageConfig = Field(
        default_factory=MultiAccountStorageConfig,
        description="Multi-account storage configuration for trust zones (Bronze/Silver/SilverExternal)"
    )

    # ========================================================================
    # Azure Storage Configuration (DEPRECATED - Use storage.* instead)
    # ========================================================================

    storage_account_name: str = Field(
        ...,  # Required field
        description="Azure Storage Account name for managed identity authentication",
        examples=["rmhazuregeo"]
    )

    bronze_container_name: str = Field(
        ...,
        description="DEPRECATED: Use storage.bronze.get_container('rasters') instead. Bronze tier container name for raw geospatial data",
        examples=["rmhazuregeobronze"],
        deprecated="Use storage.bronze.get_container() instead"
    )

    silver_container_name: str = Field(
        ...,
        description="DEPRECATED: Use storage.silver.get_container('cogs') instead. Silver tier container name for processed COGs and structured data",
        examples=["rmhazuregeosilver"],
        deprecated="Use storage.silver.get_container() instead"
    )

    gold_container_name: str = Field(
        ...,
        description="DEPRECATED: Gold tier not used in trust zone pattern. Gold tier container name for GeoParquet exports and analytics",
        examples=["rmhazuregeogold"],
        deprecated="Gold tier not used in trust zone pattern"
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

    intermediate_tiles_container: Optional[str] = Field(
        default=None,
        description="Container for intermediate raster tiles (Stage 2 output). If None, defaults to silver-tiles. Cleanup handled by separate timer trigger (NOT in ETL workflow).",
        examples=["silver-tiles", "bronze-rasters", "silver-temp"]
    )

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

    raster_target_crs: str = Field(
        default="EPSG:4326",
        description="Default target CRS for raster reprojection (WGS84 geographic coordinates)",
        examples=["EPSG:4326", "EPSG:3857", "EPSG:32637"]
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
        description="Default setting for COG processing mode (in-memory vs disk-based). "
                    "Can be overridden per-job via 'in_memory' parameter. "
                    "In-memory (True) is faster for small files (<1GB) but uses more RAM. "
                    "Disk-based (False) uses local SSD temp storage, better for large files. "
                    "Environment variable: RASTER_COG_IN_MEMORY",
    )

    raster_mosaicjson_maxzoom: int = Field(
        default=19,
        ge=0,
        le=24,
        description="Default maximum zoom level for MosaicJSON tile serving. "
                    "Can be overridden per-job via 'maxzoom' parameter. "
                    "Zoom 18 = 0.60m/pixel (standard satellite), "
                    "Zoom 19 = 0.30m/pixel (high-res satellite), "
                    "Zoom 20 = 0.15m/pixel (drone imagery), "
                    "Zoom 21 = 0.07m/pixel (very high-res drone). "
                    "Set based on your imagery's native resolution. "
                    "Environment variable: RASTER_MOSAICJSON_MAXZOOM",
    )

    # ========================================================================
    # Debug Configuration (8 NOV 2025)
    # ========================================================================

    debug_mode: bool = Field(
        default=False,
        description="Enable debug mode for verbose diagnostics. "
                    "WARNING: Increases logging overhead and log volume. "
                    "Features enabled: memory tracking, detailed timing, payload logging. "
                    "Set DEBUG_MODE=true in environment to enable.",
        examples=[True, False]
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
    # PostgreSQL Managed Identity Configuration (15 NOV 2025)
    # ========================================================================

    use_managed_identity: bool = Field(
        default=False,
        description="""Enable Azure Managed Identity for passwordless PostgreSQL authentication.

        Purpose:
            Eliminates password management by using Azure AD tokens for database authentication.
            Tokens are automatically acquired and refreshed by Azure SDK.

        Behavior:
            - When True: Uses DefaultAzureCredential to acquire PostgreSQL access tokens
            - When False: Uses traditional password-based authentication
            - Auto-detect: If running in Azure Functions without password, enables automatically

        Environment Variable: USE_MANAGED_IDENTITY

        Prerequisites:
            1. Azure Function App has system-assigned or user-assigned managed identity enabled
            2. PostgreSQL user created matching managed identity name (via pgaadauth_create_principal)
            3. Managed identity granted necessary database permissions

        Local Development:
            - Requires `az login` to use AzureCliCredential
            - Or set password fallback in local.settings.json

        Security Benefits:
            - No passwords in configuration or Key Vault
            - Tokens expire after 1 hour (automatic rotation)
            - All authentication logged in Azure AD audit logs
            - Eliminates credential theft risk

        See: docs_claude/MANAGED_IDENTITY_MIGRATION.md for setup guide
        """
    )

    managed_identity_name: Optional[str] = Field(
        default=None,
        description="""Managed identity name for PostgreSQL authentication.

        Purpose:
            Specifies the PostgreSQL user name that matches the Azure managed identity.
            This must exactly match the identity name created in PostgreSQL.

        Behavior:
            - If specified: Uses this exact name as PostgreSQL user
            - If None: Auto-generates from Function App name (WEBSITE_SITE_NAME + '-identity')
            - Example: 'rmhazuregeoapi-identity' for Function App 'rmhazuregeoapi'

        Environment Variable: MANAGED_IDENTITY_NAME

        PostgreSQL Setup:
            The managed identity user must be created in PostgreSQL using:
            SELECT * FROM pgaadauth_create_principal('rmhazuregeoapi-identity', false, false);

        Important:
            - Name must match EXACTLY (case-sensitive)
            - Must be a valid PostgreSQL identifier
            - Should follow naming convention: {function-app-name}-identity

        Default Calculation:
            - Azure Functions: {WEBSITE_SITE_NAME}-identity
            - Local Dev: 'rmhazuregeoapi-identity' (fallback)
        """
    )

    # ========================================================================
    # STAC Configuration
    # ========================================================================

    stac_default_collection: str = Field(
        default="system-rasters",
        description="""Default STAC collection for standalone raster processing.

        Purpose:
            System-managed collection for individual raster files processed via
            process_raster job (as opposed to organized datasets in dedicated collections).

        Behavior:
            - Auto-created if missing when first raster is processed
            - Used when collection_id parameter is not specified in process_raster
            - Separate from user-defined collections for organized datasets

        Usage:
            - process_raster jobs default to this collection
            - Users can override with collection_id parameter
            - Collection is auto-created with warning if doesn't exist

        Note: This separates "ad-hoc individual files" from "organized datasets"
        """
    )

    system_admin0_table: str = Field(
        default="geo.system_admin0_boundaries",
        description="""PostgreSQL table name for system admin0 (country) boundaries with ISO3 codes.

        Table structure:
            - iso3 VARCHAR(3) PRIMARY KEY (includes 'XXX' for disputed territories)
            - iso2 VARCHAR(2) (optional)
            - name TEXT (country/territory name)
            - geometry GEOMETRY(MultiPolygon, 4326)
            - status VARCHAR(20) (e.g., 'recognized', 'disputed', 'partial')

        Special ISO3 Codes:
            - 'XXX': Disputed territories (Western Sahara, Kashmir, etc.)
            - Standard ISO 3166-1 alpha-3 for recognized countries

        Usage:
            SELECT iso3 FROM {system_admin0_table}
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(...))

        Note: Custom table to handle geopolitical complexities not covered by standard ISO 3166-1
        """
    )

    h3_spatial_filter_table: str = Field(
        default="system_admin0",
        description="""Table name (without schema) for H3 land filtering during bootstrap.

        Purpose:
            Used by H3 bootstrap process to perform ONE-TIME spatial filtering
            at resolution 2 to identify land vs ocean hexagons via ST_Intersects.

        Schema:
            Table is always accessed as 'geo.{h3_spatial_filter_table}'
            (geo schema is hardcoded for user vector data)

        Table Requirements:
            - Must exist in 'geo' schema before running H3 bootstrap
            - Must have geometry column (any name - typically 'geom' or 'geometry')
            - Must contain land/country boundaries in EPSG:4326
            - Used ONLY during bootstrap - not required for normal operations

        Default Value:
            "system_admin0" - Matches actual countries polygon table name
            Can override via H3_SPATIAL_FILTER_TABLE environment variable

        Usage in H3 code:
            config = get_config()
            spatial_filter_table = f"geo.{config.h3_spatial_filter_table}"
            # Performs: ST_Intersects(h3.geom, geo.system_admin0.geom)

        Common Values:
            - "system_admin0" (default - actual table name for country polygons)
            - "system_admin0_boundaries" (alternative naming)
            - "countries" (simple naming convention)
            - "land_polygons" (custom land mask dataset)

        Note: Table must exist in geo schema before running H3 bootstrap job
        """
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
    # DuckDB Configuration - Analytical Query Engine
    # ========================================================================

    duckdb_connection_type: str = Field(
        default="memory",
        description="DuckDB connection type: 'memory' (in-memory, ephemeral) or 'persistent' (file-based)"
    )

    duckdb_database_path: Optional[str] = Field(
        default=None,
        description="Path to DuckDB database file for persistent mode (e.g., '/data/analytics.duckdb')"
    )

    duckdb_enable_spatial: bool = Field(
        default=True,
        description="Enable DuckDB spatial extension for PostGIS-like ST_* functions"
    )

    duckdb_enable_azure: bool = Field(
        default=True,
        description="Enable DuckDB azure extension for serverless blob storage queries"
    )

    duckdb_enable_httpfs: bool = Field(
        default=False,
        description="Enable DuckDB httpfs extension for HTTP/HTTPS file access (optional)"
    )

    duckdb_memory_limit: Optional[str] = Field(
        default=None,
        description="DuckDB memory limit (e.g., '1GB', '512MB'). None = unlimited."
    )

    duckdb_threads: Optional[int] = Field(
        default=None,
        description="Number of threads for DuckDB queries. None = auto-detect CPU count."
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
        default=30,
        ge=1,
        le=30,
        description="Azure Function timeout in minutes (Premium EP1 supports up to 30 minutes)"
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
    
    # Health check toggles (13 NOV 2025)
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

    # VSI (Virtual File System) health check configuration
    vsi_test_file: str = Field(
        default="dctest.tif",
        description="Test file name for VSI /vsicurl/ capability check in health endpoint. "
                    "File must exist in vsi_test_container for health check to pass."
    )

    vsi_test_container: str = Field(
        default="rmhazuregeobronze",
        description="Container name for VSI test file. Default uses legacy flat container name. "
                    "For trust zone pattern, use storage.bronze.get_container('rasters')."
    )

    # ========================================================================
    # API Endpoint Configuration (NEW - 3 NOV 2025)
    # ========================================================================

    titiler_base_url: str = Field(
        default="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net",
        description="Base URL for TiTiler-PgSTAC tile server (raster visualization). "
                    "Production URL already deployed and operational."
    )

    ogc_features_base_url: str = Field(
        default="https://rmhgeoapifn-dydhe8dddef4f7bd.eastus-01.azurewebsites.net/api/features",
        description="Base URL for OGC API - Features (vector data access). "
                    "Updated for read-only rmhgeoapifn function app (24 NOV 2025). "
                    "Placeholder until custom DNS (geospatial.rmh.org) is configured."
    )

    titiler_mode: str = Field(
        default="pgstac",
        description="TiTiler deployment mode for ETL workflows. Options:\n"
                    "  - 'vanilla': Direct /vsiaz/ blob access (simplest, no database)\n"
                    "  - 'pgstac': Database-backed STAC catalog (default, production mode)\n"
                    "  - 'xarray': Multi-dimensional datasets (future support)\n"
                    "Determines which TiTiler URL endpoints are generated during ETL."
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
        return self.intermediate_tiles_container or "silver-mosaicjson"

    def generate_titiler_urls(self, collection_id: str, item_id: str) -> dict:
        """
        Generate TiTiler-PgSTAC tile serving URLs for a raster STAC item.

        Use this for ALL raster workflows (process_raster, process_large_raster,
        process_raster_collection) to provide users with ready-to-use
        visualization endpoints.

        Args:
            collection_id: STAC collection ID (typically "cogs")
            item_id: STAC item ID (e.g., "17apr2024wv2", "antigua-april-2013")

        Returns:
            Dict with complete set of TiTiler endpoints:
            - tile_url_template: For Leaflet/Mapbox ({z}/{x}/{y} placeholders)
            - preview_url: PNG thumbnail (512px default)
            - info_url: Raster metadata (bands, stats, data type)
            - bounds_url: Spatial extent in EPSG:4326
            - map_viewer_url: Built-in Leaflet interactive viewer

        Example:
            >>> config = get_config()
            >>> urls = config.generate_titiler_urls("cogs", "17apr2024wv2")
            >>> urls["preview_url"]
            'https://rmhtitiler-.../collections/cogs/items/17apr2024wv2/preview.png?width=512'

        Notes:
            - URLs work immediately after STAC item is created in PgSTAC
            - No additional TiTiler configuration required
            - Supports OGC Tiles 1.0 standard parameters (rescale, colormap, etc.)
            - tile_url_template uses {z}/{x}/{y} placeholders for web mapping libraries
        """
        base = self.titiler_base_url.rstrip('/')

        return {
            "tile_url_template": f"{base}/collections/{collection_id}/items/{item_id}/WebMercatorQuad/tiles/{{z}}/{{x}}/{{y}}",
            "preview_url": f"{base}/collections/{collection_id}/items/{item_id}/preview.png?width=512",
            "info_url": f"{base}/collections/{collection_id}/items/{item_id}/info",
            "bounds_url": f"{base}/collections/{collection_id}/items/{item_id}/bounds",
            "map_viewer_url": f"{base}/collections/{collection_id}/items/{item_id}/WebMercatorQuad/map.html"
        }

    def generate_vanilla_titiler_urls(self, container: str, blob_name: str) -> dict:
        """
        Generate Vanilla TiTiler URLs using direct /vsiaz/ COG access.

        Use this when you have a COG blob path and want immediate visualization
        WITHOUT requiring PgSTAC database lookup. Works with managed identity
        authentication.

        Args:
            container: Azure Storage container name (e.g., "silver-cogs")
            blob_name: Blob path within container (e.g., "05APR13082706_cog.tif")

        Returns:
            Dict with vanilla TiTiler endpoints using /vsiaz/ paths:
            - viewer_url: Interactive map viewer (PRIMARY - share this!)
            - thumbnail_url: PNG thumbnail (256px)
            - info_url: COG metadata JSON
            - info_geojson_url: COG bounds as GeoJSON
            - statistics_url: Band statistics (min/max/mean/stddev)
            - tilejson_url: TileJSON specification for web maps
            - tiles_url_template: XYZ tile URL template

        Example:
            >>> config = get_config()
            >>> urls = config.generate_vanilla_titiler_urls("silver-cogs", "05APR13082706_cog.tif")
            >>> urls["viewer_url"]
            'https://rmhtitiler-.../cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/...'

        Notes:
            - URLs work IMMEDIATELY after COG creation (no PgSTAC required)
            - Managed identity authentication handles Azure Storage access
            - viewer_url is the PRIMARY URL to share with end users
            - See STAC-INTEGRATION-GUIDE.md for additional usage patterns
        """
        import urllib.parse

        base = self.titiler_base_url.rstrip('/')
        vsiaz_path = f"/vsiaz/{container}/{blob_name}"
        # URL-encode the path for safe use in query parameters
        encoded_vsiaz = urllib.parse.quote(vsiaz_path, safe='')

        return {
            "viewer_url": f"{base}/cog/WebMercatorQuad/map.html?url={encoded_vsiaz}",
            "thumbnail_url": f"{base}/cog/preview.png?url={encoded_vsiaz}&max_size=256",
            "info_url": f"{base}/cog/info?url={encoded_vsiaz}",
            "info_geojson_url": f"{base}/cog/info.geojson?url={encoded_vsiaz}",
            "statistics_url": f"{base}/cog/statistics?url={encoded_vsiaz}",
            "tilejson_url": f"{base}/cog/WebMercatorQuad/tilejson.json?url={encoded_vsiaz}",
            "tiles_url_template": f"{base}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={encoded_vsiaz}"
        }

    def generate_titiler_urls_unified(
        self,
        mode: str,  # Literal["cog", "mosaicjson", "pgstac"] - using str for Python 3.9 compatibility
        container: str = None,
        blob_name: str = None,
        search_id: str = None
    ) -> dict:
        """
        Generate TiTiler URLs for all three access patterns (10 NOV 2025).

        Consolidates three TiTiler visualization patterns into single method:
        1. Single COG - Direct /vsiaz/ access to individual raster
        2. MosaicJSON - Collection of COGs as single layer
        3. PgSTAC Search - Dynamic queries across STAC catalog

        Args:
            mode: URL generation mode
                - "cog": Single COG via /vsiaz/ path (IMPLEMENTED)
                - "mosaicjson": MosaicJSON via /vsiaz/ path (PLACEHOLDER - pending pattern verification)
                - "pgstac": PgSTAC search results via search_id (NOT IMPLEMENTED - future enhancement)
            container: Azure container name (required for cog/mosaicjson modes)
            blob_name: Blob path within container (required for cog/mosaicjson modes)
            search_id: PgSTAC search hash (required for pgstac mode)

        Returns:
            Dict with TiTiler URLs appropriate for the mode:
            - viewer_url: Interactive map viewer (PRIMARY URL)
            - info_url: COG/mosaic metadata JSON
            - preview_url: PNG thumbnail
            - tiles_url_template: XYZ tile template for web maps
            - (additional URLs vary by mode)

        Raises:
            ValueError: If required parameters missing for selected mode
            NotImplementedError: If mode="mosaicjson" or mode="pgstac" (not yet implemented)

        Example - Single COG:
            >>> config = get_config()
            >>> urls = config.generate_titiler_urls_unified(
            ...     mode="cog",
            ...     container="silver-cogs",
            ...     blob_name="raster.tif"
            ... )
            >>> urls["viewer_url"]
            'https://rmhtitiler-.../cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/raster.tif'

        Notes:
            - All URLs use correct /cog/ endpoint (NOT STAC API /collections/ endpoints)
            - See TITILER-VALIDATION-TASK.md lines 124-174 for URL format details
            - MosaicJSON and PgSTAC modes are placeholders pending implementation
        """
        import urllib.parse

        base = self.titiler_base_url.rstrip('/')

        # ========================================================================
        # MODE 1: Single COG (IMPLEMENTED)
        # ========================================================================
        if mode == "cog":
            # Validate required parameters
            if not container or not blob_name:
                raise ValueError(
                    "mode='cog' requires container and blob_name parameters. "
                    f"Got: container={container}, blob_name={blob_name}"
                )

            # Construct /vsiaz/ path and URL-encode
            vsiaz_path = f"/vsiaz/{container}/{blob_name}"
            encoded_vsiaz = urllib.parse.quote(vsiaz_path, safe='')

            # Generate URLs (same as generate_vanilla_titiler_urls)
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

        # ========================================================================
        # MODE 2: MosaicJSON (IMPLEMENTED - 10 NOV 2025)
        # ========================================================================
        elif mode == "mosaicjson":
            # Validate required parameters
            if not container or not blob_name:
                raise ValueError(
                    "mode='mosaicjson' requires container and blob_name parameters. "
                    f"Got: container={container}, blob_name={blob_name}"
                )

            # Validate that blob_name is a JSON file
            if not blob_name.endswith('.json'):
                raise ValueError(
                    f"mode='mosaicjson' requires blob_name to be a .json file. "
                    f"Got: {blob_name}"
                )

            # Construct /vsiaz/ path to MosaicJSON file and URL-encode
            vsiaz_path = f"/vsiaz/{container}/{blob_name}"
            encoded_vsiaz = urllib.parse.quote(vsiaz_path, safe='')

            # Generate URLs using /mosaicjson/ endpoint
            # Reference: COG_MOSAIC.md lines 446-465
            return {
                "viewer_url": f"{base}/mosaicjson/WebMercatorQuad/map.html?url={encoded_vsiaz}",
                "info_url": f"{base}/mosaicjson/info?url={encoded_vsiaz}",
                "bounds_url": f"{base}/mosaicjson/bounds?url={encoded_vsiaz}",
                "tilejson_url": f"{base}/mosaicjson/WebMercatorQuad/tilejson.json?url={encoded_vsiaz}",
                "tiles_url_template": f"{base}/mosaicjson/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={encoded_vsiaz}",
                "assets_url_template": f"{base}/mosaicjson/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}/assets?url={encoded_vsiaz}",
                "point_url_template": f"{base}/mosaicjson/point/{{lon}},{{lat}}?url={encoded_vsiaz}"
            }

        # ========================================================================
        # MODE 3: PgSTAC Search (FUTURE ENHANCEMENT)
        # ========================================================================
        elif mode == "pgstac":
            # TODO (FUTURE): Implement PgSTAC search workflow
            #
            # Requires two-step process:
            # 1. Create search in PgSTAC database:
            #    POST /searches with CQL2 query body:
            #    {
            #        "collections": ["system-rasters"],
            #        "bbox": [minx, miny, maxx, maxy],
            #        "datetime": "2024-01-01/2024-12-31"
            #    }
            # 2. Extract search_id from response (SHA256 hash)
            # 3. Generate URLs using search_id:
            #    /searches/{search_id}/WebMercatorQuad/map.html
            #
            # Benefits:
            # - Dynamic queries across entire STAC catalog
            # - Automatic mosaicking of matching items
            # - No pre-generated MosaicJSON files needed
            #
            # Implementation notes:
            # - Requires PgSTAC search API endpoint (separate from TiTiler)
            # - Search IDs are deterministic (same query = same ID)
            # - Can be cached for performance
            #
            # Reference: TITILER-VALIDATION-TASK.md lines 148-168
            raise NotImplementedError(
                "PgSTAC search URL generation not yet implemented. "
                "Requires PgSTAC search creation workflow. "
                "For now, search IDs must be created manually and URLs constructed directly: "
                f"{base}/searches/{{search_id}}/WebMercatorQuad/map.html"
            )

        else:
            raise ValueError(
                f"Invalid mode: {mode}. Must be one of: 'cog', 'mosaicjson', 'pgstac'"
            )

    def generate_ogc_features_url(self, collection_id: str) -> str:
        """
        Generate OGC API - Features collection URL for vector data.

        Use this for ALL vector workflows (ingest_vector) to provide users
        with standardized GeoJSON access to their PostGIS tables.

        Args:
            collection_id: Collection name (same as PostGIS table name)

        Returns:
            OGC Features collection URL for querying vector features

        Example:
            >>> config = get_config()
            >>> url = config.generate_ogc_features_url("acled_1997")
            >>> url
            'https://rmhgeoapibeta-.../api/features/collections/acled_1997'

        Available Operations:
            - GET /collections/{id} - Collection metadata (bbox, feature count)
            - GET /collections/{id}/items - Query features (supports bbox, limit, offset)
            - GET /collections/{id}/items/{feature_id} - Single feature by ID

        Notes:
            - Base URL is placeholder until custom DNS is configured
            - Will become https://geospatial.rmh.org/api/features/collections/{id}
            - Easy update: Single environment variable (OGC_FEATURES_BASE_URL)
            - OGC API - Features Core 1.0 compliant
        """
        return f"{self.ogc_features_base_url.rstrip('/')}/collections/{collection_id}"

    def generate_vector_viewer_url(self, collection_id: str) -> str:
        """
        Generate interactive vector viewer URL for PostGIS collection.

        Use this for ALL vector workflows (ingest_vector) to provide data curators
        with direct link to visual QA viewer with Leaflet map.

        Args:
            collection_id: Collection name (same as PostGIS table name)

        Returns:
            Vector viewer URL with collection parameter

        Example:
            >>> config = get_config()
            >>> url = config.generate_vector_viewer_url("acled_csv")
            >>> url
            'https://rmhazuregeoapi-.../api/vector/viewer?collection=acled_csv'

        Features:
            - Interactive Leaflet map with pan/zoom
            - Load 100, 500, or All features (up to 10,000)
            - Click features to see properties popup
            - QA workflow section (Approve/Reject buttons)
            - Fetches data from OGC Features API

        Notes:
            - Base URL derived from ogc_features_base_url
            - Viewer endpoint shares same host as OGC Features API
            - Returns self-contained HTML page (no external dependencies beyond Leaflet CDN)
        """
        # Extract base URL from ogc_features_base_url (remove /api/features suffix)
        base_url = self.ogc_features_base_url.rstrip('/')
        # Remove /api/features to get host base
        if base_url.endswith('/api/features'):
            base_url = base_url[:-len('/api/features')]

        return f"{base_url}/api/vector/viewer?collection={collection_id}"

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

    @field_validator('titiler_mode')
    @classmethod
    def validate_titiler_mode(cls, v: str) -> str:
        """Validate TiTiler mode is one of the supported deployment types"""
        valid_modes = {'vanilla', 'pgstac', 'xarray'}
        if v.lower() not in valid_modes:
            raise ValueError(f"titiler_mode must be one of: {', '.join(valid_modes)}")
        return v.lower()
    
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

            # STAC
            stac_default_collection=os.environ.get('STAC_DEFAULT_COLLECTION', 'system-rasters'),

            # Vector ETL
            vector_pickle_container=os.environ.get('VECTOR_PICKLE_CONTAINER', 'rmhazuregeotemp'),
            vector_pickle_prefix=os.environ.get('VECTOR_PICKLE_PREFIX', 'temp/vector_etl'),
            
            # Security
            key_vault_name=os.environ.get('KEY_VAULT', 'rmhkeyvault'),
            key_vault_database_secret=os.environ.get('KEY_VAULT_DATABASE_SECRET', 'postgis-password'),
            
            # Application
            function_timeout_minutes=int(os.environ.get('FUNCTION_TIMEOUT_MINUTES', '30')),
            max_retry_attempts=int(os.environ.get('MAX_RETRY_ATTEMPTS', '3')),
            log_level=os.environ.get('LOG_LEVEL', 'INFO'),
            enable_database_health_check=os.environ.get('ENABLE_DATABASE_HEALTH_CHECK', 'true').lower() == 'true',
            debug_mode=os.environ.get('DEBUG_MODE', 'false').lower() == 'true',
            
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

            # Raster pipeline configuration
            raster_mosaicjson_maxzoom=int(os.environ.get('RASTER_MOSAICJSON_MAXZOOM', '19')),

            # API endpoint configuration
            titiler_base_url=os.environ.get('TITILER_BASE_URL', 'https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net'),
            ogc_features_base_url=os.environ.get('OGC_FEATURES_BASE_URL', 'https://rmhgeoapifn-dydhe8dddef4f7bd.eastus-01.azurewebsites.net/api/features'),
            titiler_mode=os.environ.get('TITILER_MODE', 'pgstac'),
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


def get_postgres_connection_string(config: Optional[AppConfig] = None) -> str:
    """
    Get PostgreSQL connection string with managed identity support.

    This function provides a centralized way to get database connection strings
    that respects the USE_MANAGED_IDENTITY environment variable.

    **IMPORTANT**: Use this function instead of config.postgis_connection_string
    for all database connections to ensure managed identity authentication works.

    How it works:
    -------------
    1. Creates a PostgreSQLRepository instance (handles managed identity)
    2. Returns the connection string from the repository
    3. The repository automatically uses managed identity if USE_MANAGED_IDENTITY=true

    Parameters:
    ----------
    config : Optional[AppConfig]
        Configuration object. If not provided, uses get_config().

    Returns:
    -------
    str
        PostgreSQL connection string with managed identity token (if enabled)
        or password-based connection string (if managed identity disabled).

    Raises:
    ------
    RuntimeError
        If connection string cannot be built (e.g., managed identity fails
        and no password available).

    Example:
    -------
    ```python
    from config import get_postgres_connection_string
    import psycopg

    # Get connection string (respects managed identity)
    conn_str = get_postgres_connection_string()

    # Use with psycopg
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    ```

    Migration Guide:
    ---------------
    **OLD PATTERN (broken with managed identity)**:
    ```python
    config = get_config()
    connection_string = config.postgis_connection_string  # ❌ Doesn't support managed identity
    with psycopg.connect(connection_string) as conn:
        ...
    ```

    **NEW PATTERN (works with managed identity)**:
    ```python
    from config import get_postgres_connection_string
    connection_string = get_postgres_connection_string()  # ✅ Supports managed identity
    with psycopg.connect(connection_string) as conn:
        ...
    ```

    See Also:
    --------
    - infrastructure/postgresql.py: PostgreSQLRepository class
    - docs_claude/MANAGED_IDENTITY_MIGRATION.md: Full migration guide
    """
    from infrastructure.postgresql import PostgreSQLRepository

    if config is None:
        config = get_config()

    try:
        repo = PostgreSQLRepository(config=config)
        return repo.conn_string
    except Exception as e:
        raise RuntimeError(f"Failed to get PostgreSQL connection string: {str(e)}") from e

