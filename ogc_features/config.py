# ============================================================================
# CLAUDE CONTEXT - OGC FEATURES CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Standalone Configuration - OGC Features API
# PURPOSE: Self-contained configuration management for OGC Features API
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: OGCFeaturesConfig, get_ogc_config
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: OGCFeaturesConfig
# DEPENDENCIES: pydantic, os
# SOURCE: Environment variables (no dependency on main app config)
# SCOPE: OGC Features API configuration only
# VALIDATION: Pydantic v2 validation
# PATTERNS: Settings Pattern, Singleton via cached function
# ENTRY_POINTS: from ogc_features.config import get_ogc_config
# INDEX: OGCFeaturesConfig:48, get_ogc_config:168
# ============================================================================

"""
OGC Features API Configuration - Standalone

Completely independent configuration system for OGC Features API.
NO dependencies on main application's config.py.

Environment Variables:
    Required:
    - POSTGIS_HOST: PostgreSQL hostname
    - POSTGIS_DATABASE: Database name
    - POSTGIS_USER: Database user
    - POSTGIS_PASSWORD: Database password

    Optional:
    - POSTGIS_PORT: PostgreSQL port (default: 5432)
    - OGC_SCHEMA: Schema containing vector tables (default: "geo")
    - OGC_GEOMETRY_COLUMN: Default geometry column name (default: "geom")
    - OGC_DEFAULT_LIMIT: Default feature limit (default: 100)
    - OGC_MAX_LIMIT: Maximum feature limit (default: 10000)
    - OGC_DEFAULT_PRECISION: Coordinate precision (default: 6)
    - OGC_BASE_URL: Base URL for self links (default: auto-detect)

Author: Robert and Geospatial Claude Legion
Date: 29 OCT 2025
"""

import os
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class OGCFeaturesConfig(BaseModel):
    """
    Configuration for OGC Features API - completely standalone.

    This configuration is independent of the main application's config.py
    and can be deployed in a separate Function App.
    """

    # PostgreSQL Connection
    postgis_host: str = Field(
        default_factory=lambda: os.getenv("POSTGIS_HOST", ""),
        description="PostgreSQL hostname"
    )
    postgis_port: int = Field(
        default_factory=lambda: int(os.getenv("POSTGIS_PORT", "5432")),
        description="PostgreSQL port"
    )
    postgis_database: str = Field(
        default_factory=lambda: os.getenv("POSTGIS_DATABASE", ""),
        description="PostgreSQL database name"
    )
    postgis_user: str = Field(
        default_factory=lambda: os.getenv("POSTGIS_USER", ""),
        description="PostgreSQL username"
    )
    postgis_password: str = Field(
        default_factory=lambda: os.getenv("POSTGIS_PASSWORD", ""),
        description="PostgreSQL password"
    )

    # OGC Features API Settings
    ogc_schema: str = Field(
        default_factory=lambda: os.getenv("OGC_SCHEMA", "geo"),
        description="PostgreSQL schema containing vector tables"
    )
    ogc_geometry_column: str = Field(
        default_factory=lambda: os.getenv("OGC_GEOMETRY_COLUMN", "geom"),
        description="Default geometry column name (use 'shape' for ArcGIS)"
    )
    ogc_default_limit: int = Field(
        default_factory=lambda: int(os.getenv("OGC_DEFAULT_LIMIT", "100")),
        ge=1,
        le=10000,
        description="Default number of features to return"
    )
    ogc_max_limit: int = Field(
        default_factory=lambda: int(os.getenv("OGC_MAX_LIMIT", "10000")),
        ge=1,
        description="Maximum number of features allowed per request"
    )
    ogc_default_precision: int = Field(
        default_factory=lambda: int(os.getenv("OGC_DEFAULT_PRECISION", "6")),
        ge=0,
        le=15,
        description="Default coordinate precision (decimal places)"
    )
    ogc_base_url: Optional[str] = Field(
        default_factory=lambda: os.getenv("OGC_BASE_URL"),
        description="Base URL for self links (auto-detected if not set)"
    )

    # Performance Settings
    query_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("OGC_QUERY_TIMEOUT", "30")),
        ge=1,
        le=300,
        description="Maximum query execution time in seconds"
    )

    # Validation Settings (for production readiness)
    enable_validation: bool = Field(
        default_factory=lambda: os.getenv("OGC_ENABLE_VALIDATION", "false").lower() == "true",
        description="Enable table optimization validation checks (spatial indexes, primary keys, etc.)"
    )

    @field_validator("postgis_host", "postgis_database", "postgis_user", "postgis_password")
    @classmethod
    def validate_required(cls, v: str, info) -> str:
        """Ensure required PostgreSQL fields are not empty."""
        if not v:
            raise ValueError(f"{info.field_name} is required - set {info.field_name.upper()} environment variable")
        return v

    def get_connection_string(self) -> str:
        """
        Build PostgreSQL connection string with managed identity support.

        ARCHITECTURE PRINCIPLE (16 NOV 2025):
        All database connections must support managed identity authentication.
        This method now uses the main config's helper function which respects
        USE_MANAGED_IDENTITY environment variable.

        Returns:
            PostgreSQL connection string (managed identity or password-based)
        """
        # Use the main application's helper function for managed identity support
        # This ensures OGC Features respects USE_MANAGED_IDENTITY=true
        from config import get_postgres_connection_string
        return get_postgres_connection_string()

    def get_base_url(self, request_url: Optional[str] = None) -> str:
        """
        Get base URL for self links.

        Args:
            request_url: Current request URL for auto-detection

        Returns:
            Base URL (configured or auto-detected)
        """
        if self.ogc_base_url:
            return self.ogc_base_url.rstrip("/")

        if request_url:
            # Auto-detect from request URL
            parts = request_url.split("/api/features")
            if parts:
                return parts[0]

        return "http://localhost:7071"  # Local development fallback


# Singleton instance cache
_config_cache: Optional[OGCFeaturesConfig] = None


def get_ogc_config() -> OGCFeaturesConfig:
    """
    Get singleton OGC Features configuration instance.

    Returns:
        Cached configuration instance

    Raises:
        ValueError: If required environment variables are missing
    """
    global _config_cache

    if _config_cache is None:
        _config_cache = OGCFeaturesConfig()

    return _config_cache
