# ============================================================================
# CLAUDE CONTEXT - STORAGE CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New module - Phase 1 of config.py refactoring (20 NOV 2025)
# PURPOSE: Azure Storage configuration - COG tiers, multi-account trust zones
# LAST_REVIEWED: 20 NOV 2025
# EXPORTS: CogTier, CogTierProfile, COG_TIER_PROFILES, StorageAccountConfig, MultiAccountStorageConfig, StorageConfig, determine_applicable_tiers
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: CogTierProfile, StorageAccountConfig, MultiAccountStorageConfig, StorageConfig
# DEPENDENCIES: pydantic, os, typing, enum
# SOURCE: Environment variables (STORAGE_ACCOUNT_NAME, SILVEREXT_CONNECTION_STRING)
# SCOPE: Storage-specific configuration
# VALIDATION: Pydantic v2 validation
# PATTERNS: Value objects, composition
# ENTRY_POINTS: from config import StorageConfig, CogTier, determine_applicable_tiers
# INDEX: CogTier:40, CogTierProfile:72, COG_TIER_PROFILES:183, determine_applicable_tiers:230, StorageAccountConfig:270, MultiAccountStorageConfig:338
# ============================================================================

"""
Azure Storage Configuration - COG Tiers and Multi-Account Trust Zones

Provides configuration for:
- COG tier profiles (VISUALIZATION, ANALYSIS, ARCHIVE)
- Multi-account storage pattern (Bronze, Silver, SilverExternal, Gold)
- Container naming conventions
- Storage access tiers

This module was extracted from config.py (lines 59-494) as part of the
god object refactoring (20 NOV 2025).
"""

import os
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field

from .defaults import StorageDefaults, AzureDefaults, RasterDefaults


# ============================================================================
# COG TIER CONFIGURATION
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
# MULTI-ACCOUNT STORAGE CONFIGURATION
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

    Environment Variable Pattern (21 NOV 2025):
    Each container can be overridden via environment variable, falling back to defaults.
    Each zone can have its own storage account.

    Environment Variables:
    ----------------------
    Storage Accounts (one per zone):
        BRONZE_STORAGE_ACCOUNT    - Bronze zone account (default: STORAGE_ACCOUNT_NAME or "rmhazuregeo")
        SILVER_STORAGE_ACCOUNT    - Silver zone account (default: STORAGE_ACCOUNT_NAME or "rmhazuregeo")
        SILVEREXT_STORAGE_ACCOUNT - SilverExt zone account (default: STORAGE_ACCOUNT_NAME or "rmhazuregeo")
        GOLD_STORAGE_ACCOUNT      - Gold zone account (default: STORAGE_ACCOUNT_NAME or "rmhazuregeo")

    Bronze Containers (input/staging):
        BRONZE_VECTORS_CONTAINER  - Vector uploads (default: "bronze-vectors")
        BRONZE_RASTERS_CONTAINER  - Raster uploads (default: "bronze-rasters")
        BRONZE_MISC_CONTAINER     - Misc files (default: "bronze-misc")
        BRONZE_TEMP_CONTAINER     - Temp processing (default: "bronze-temp")

    Silver Containers (processed/internal):
        SILVER_VECTORS_CONTAINER  - Processed vectors (default: "silver-vectors")
        SILVER_RASTERS_CONTAINER  - Processed rasters (default: "silver-rasters")
        SILVER_COGS_CONTAINER     - Cloud Optimized GeoTIFFs (default: "silver-cogs")
        SILVER_TILES_CONTAINER    - Raster tiles (default: "silver-tiles")
        SILVER_MOSAICJSON_CONTAINER - MosaicJSON files (default: "silver-mosaicjson")
        SILVER_STAC_ASSETS_CONTAINER - STAC assets (default: "silver-stac-assets")
        SILVER_MISC_CONTAINER     - Misc files (default: "silver-misc")
        SILVER_TEMP_CONTAINER     - Temp processing (default: "silver-temp")

    SilverExt Containers (airgapped external):
        SILVEREXT_VECTORS_CONTAINER, SILVEREXT_COGS_CONTAINER, etc.

    Gold Containers (analytics exports):
        GOLD_GEOPARQUET_CONTAINER - GeoParquet exports (default: "gold-geoparquet")
        GOLD_H3_GRIDS_CONTAINER   - H3 grid files (default: "gold-h3-grids")
        GOLD_TEMP_CONTAINER       - Temp analytics (default: "gold-temp")

    Trust Zone Pattern:
    - Bronze: Untrusted raw data (user uploads) - INPUT
    - Silver: Trusted processed data (COGs, vectors) - INTERNAL
    - SilverExternal: Airgapped secure replica - EXTERNAL
    - Gold: Analytics-ready exports (GeoParquet, H3) - ANALYTICS

    Example Deployment Scenarios:
    ----------------------------
    1. Development (single account, all containers):
       STORAGE_ACCOUNT_NAME=rmhazuregeo
       # All zones use same account, default container names

    2. Production (3 accounts):
       BRONZE_STORAGE_ACCOUNT=rmhgeo-bronze
       SILVER_STORAGE_ACCOUNT=rmhgeo-silver
       SILVEREXT_STORAGE_ACCOUNT=rmhgeo-external

    3. Custom container names (legacy compatibility):
       BRONZE_RASTERS_CONTAINER=rmhazuregeobronze
       BRONZE_VECTORS_CONTAINER=rmhazuregeobronze
       # Both rasters and vectors in same container
    """

    # BRONZE: Untrusted raw data zone (INPUT)
    bronze: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv(
                "BRONZE_STORAGE_ACCOUNT",
                os.getenv("STORAGE_ACCOUNT_NAME", AzureDefaults.STORAGE_ACCOUNT_NAME)
            ),
            container_prefix="bronze",
            vectors=os.getenv("BRONZE_VECTORS_CONTAINER", StorageDefaults.BRONZE_VECTORS),
            rasters=os.getenv("BRONZE_RASTERS_CONTAINER", StorageDefaults.BRONZE_RASTERS),
            misc=os.getenv("BRONZE_MISC_CONTAINER", StorageDefaults.BRONZE_MISC),
            temp=os.getenv("BRONZE_TEMP_CONTAINER", StorageDefaults.BRONZE_TEMP),
            # Not used in Bronze (no processed outputs):
            cogs=os.getenv("BRONZE_COGS_CONTAINER", StorageDefaults.NOT_USED),
            tiles=os.getenv("BRONZE_TILES_CONTAINER", StorageDefaults.NOT_USED),
            mosaicjson=os.getenv("BRONZE_MOSAICJSON_CONTAINER", StorageDefaults.NOT_USED),
            stac_assets=os.getenv("BRONZE_STAC_ASSETS_CONTAINER", StorageDefaults.NOT_USED)
        )
    )

    # SILVER: Trusted processed data + REST API serving (INTERNAL)
    silver: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv(
                "SILVER_STORAGE_ACCOUNT",
                os.getenv("STORAGE_ACCOUNT_NAME", AzureDefaults.STORAGE_ACCOUNT_NAME)
            ),
            container_prefix="silver",
            vectors=os.getenv("SILVER_VECTORS_CONTAINER", StorageDefaults.SILVER_VECTORS),
            rasters=os.getenv("SILVER_RASTERS_CONTAINER", StorageDefaults.SILVER_RASTERS),
            cogs=os.getenv("SILVER_COGS_CONTAINER", StorageDefaults.SILVER_COGS),
            tiles=os.getenv("SILVER_TILES_CONTAINER", StorageDefaults.SILVER_TILES),
            mosaicjson=os.getenv("SILVER_MOSAICJSON_CONTAINER", StorageDefaults.SILVER_MOSAICJSON),
            stac_assets=os.getenv("SILVER_STAC_ASSETS_CONTAINER", StorageDefaults.SILVER_STAC_ASSETS),
            misc=os.getenv("SILVER_MISC_CONTAINER", StorageDefaults.SILVER_MISC),
            temp=os.getenv("SILVER_TEMP_CONTAINER", StorageDefaults.SILVER_TEMP)
        )
    )

    # SILVER EXTERNAL: Airgapped secure environment replica (EXTERNAL)
    silverext: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv(
                "SILVEREXT_STORAGE_ACCOUNT",
                os.getenv("STORAGE_ACCOUNT_NAME", AzureDefaults.STORAGE_ACCOUNT_NAME)
            ),
            container_prefix="silverext",
            vectors=os.getenv("SILVEREXT_VECTORS_CONTAINER", StorageDefaults.SILVEREXT_VECTORS),
            rasters=os.getenv("SILVEREXT_RASTERS_CONTAINER", StorageDefaults.SILVEREXT_RASTERS),
            cogs=os.getenv("SILVEREXT_COGS_CONTAINER", StorageDefaults.SILVEREXT_COGS),
            tiles=os.getenv("SILVEREXT_TILES_CONTAINER", StorageDefaults.SILVEREXT_TILES),
            mosaicjson=os.getenv("SILVEREXT_MOSAICJSON_CONTAINER", StorageDefaults.SILVEREXT_MOSAICJSON),
            stac_assets=os.getenv("SILVEREXT_STAC_ASSETS_CONTAINER", StorageDefaults.SILVEREXT_STAC_ASSETS),
            misc=os.getenv("SILVEREXT_MISC_CONTAINER", StorageDefaults.SILVEREXT_MISC),
            temp=os.getenv("SILVEREXT_TEMP_CONTAINER", StorageDefaults.SILVEREXT_TEMP)
        )
    )

    # GOLD: Analytics-ready exports (GeoParquet, H3 grids, DuckDB-optimized)
    gold: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv(
                "GOLD_STORAGE_ACCOUNT",
                os.getenv("STORAGE_ACCOUNT_NAME", AzureDefaults.STORAGE_ACCOUNT_NAME)
            ),
            container_prefix="gold",
            vectors=os.getenv("GOLD_GEOPARQUET_CONTAINER", StorageDefaults.GOLD_GEOPARQUET),
            rasters=os.getenv("GOLD_RASTERS_CONTAINER", StorageDefaults.NOT_USED),
            cogs=os.getenv("GOLD_COGS_CONTAINER", StorageDefaults.NOT_USED),
            tiles=os.getenv("GOLD_TILES_CONTAINER", StorageDefaults.NOT_USED),
            mosaicjson=os.getenv("GOLD_MOSAICJSON_CONTAINER", StorageDefaults.NOT_USED),
            stac_assets=os.getenv("GOLD_STAC_ASSETS_CONTAINER", StorageDefaults.NOT_USED),
            misc=os.getenv("GOLD_H3_GRIDS_CONTAINER", StorageDefaults.GOLD_H3_GRIDS),
            temp=os.getenv("GOLD_TEMP_CONTAINER", StorageDefaults.GOLD_TEMP)
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
            → value of BRONZE_VECTORS_CONTAINER or "bronze-vectors"

            storage.get_account("gold").get_container("misc")
            → value of GOLD_H3_GRIDS_CONTAINER or "gold-h3-grids"

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

    @classmethod
    def from_environment(cls):
        """Load storage configuration from environment variables."""
        return cls()  # Uses default_factory for each field

    def debug_dict(self) -> dict:
        """Return debug-friendly configuration showing resolved values."""
        return {
            "bronze": {
                "account": self.bronze.account_name,
                "vectors": self.bronze.vectors,
                "rasters": self.bronze.rasters
            },
            "silver": {
                "account": self.silver.account_name,
                "vectors": self.silver.vectors,
                "cogs": self.silver.cogs
            },
            "silverext": {
                "account": self.silverext.account_name,
                "vectors": self.silverext.vectors,
                "cogs": self.silverext.cogs
            },
            "gold": {
                "account": self.gold.account_name,
                "geoparquet": self.gold.vectors,
                "h3_grids": self.gold.misc
            }
        }


class StorageConfig(MultiAccountStorageConfig):
    """
    Azure Storage configuration for multi-account trust zones.

    Inherits from MultiAccountStorageConfig to provide direct access to storage zones:
    - config.storage.bronze.get_container('vectors')
    - config.storage.silver.get_container('cogs')
    - config.storage.gold.get_container('misc')

    This eliminates the nested .storage.storage pattern.
    """
    pass
