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

        ARCHITECTURE PRINCIPLE (24 NOV 2025):
        All database connections must support managed identity authentication.
        This method uses the same authentication priority chain as PostgreSQLRepository:

        Authentication Priority:
        1. User-Assigned Managed Identity (if MANAGED_IDENTITY_CLIENT_ID is set)
        2. System-Assigned Managed Identity (if running in Azure with WEBSITE_SITE_NAME)
        3. Password Authentication (if POSTGIS_PASSWORD is set)

        Returns:
            PostgreSQL connection string (managed identity or password-based)
        """
        import os
        import logging
        logger = logging.getLogger(__name__)

        # Get environment variables for detection
        client_id = os.getenv("MANAGED_IDENTITY_CLIENT_ID")
        website_name = os.getenv("WEBSITE_SITE_NAME")
        password = self.postgis_password

        # Priority 1: User-Assigned Managed Identity
        if client_id:
            identity_name = os.getenv("MANAGED_IDENTITY_NAME", "rmhpgflexadmin")
            logger.info(f"🔐 [OGC AUTH] Using USER-ASSIGNED managed identity: {identity_name}")
            return self._build_managed_identity_connection_string(
                client_id=client_id,
                identity_name=identity_name
            )

        # Priority 2: System-Assigned Managed Identity (running in Azure)
        if website_name:
            identity_name = os.getenv("MANAGED_IDENTITY_NAME", website_name)
            logger.info(f"🔐 [OGC AUTH] Using SYSTEM-ASSIGNED managed identity: {identity_name}")
            return self._build_managed_identity_connection_string(
                client_id=None,
                identity_name=identity_name
            )

        # Priority 3: Password Authentication
        if password:
            logger.info("🔑 [OGC AUTH] Using PASSWORD authentication (local development mode)")
            return (
                f"host={self.postgis_host} "
                f"port={self.postgis_port} "
                f"dbname={self.postgis_database} "
                f"user={self.postgis_user} "
                f"password={self.postgis_password} "
                f"sslmode=require"
            )

        # Priority 4: FAIL - No valid credentials
        error_msg = (
            "❌ [OGC] NO DATABASE CREDENTIALS FOUND!\n"
            "Please configure one of the following:\n"
            "  1. User-Assigned Identity: Set MANAGED_IDENTITY_CLIENT_ID + MANAGED_IDENTITY_NAME\n"
            "  2. System-Assigned Identity: Deploy to Azure (auto-detected via WEBSITE_SITE_NAME)\n"
            "  3. Password Auth: Set POSTGIS_PASSWORD environment variable"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    def _build_managed_identity_connection_string(
        self,
        client_id: str = None,
        identity_name: str = "rmhpgflexadmin"
    ) -> str:
        """
        Build PostgreSQL connection string using Azure Managed Identity.

        This method acquires an access token from Azure AD and uses it as
        the password in the PostgreSQL connection string.

        Args:
            client_id: Client ID for user-assigned managed identity.
                      If None, uses system-assigned identity.
            identity_name: PostgreSQL user name matching the managed identity.
                          Defaults to 'rmhpgflexadmin' for user-assigned identity.

        Returns:
            PostgreSQL connection string with managed identity token.

        Raises:
            RuntimeError: If token acquisition fails.
        """
        from azure.identity import ManagedIdentityCredential
        from azure.core.exceptions import ClientAuthenticationError
        import logging
        logger = logging.getLogger(__name__)

        try:
            if client_id:
                logger.debug(f"🔑 [OGC] Acquiring token for user-assigned identity (client_id: {client_id[:8]}...)")
                credential = ManagedIdentityCredential(client_id=client_id)
            else:
                logger.debug("🔑 [OGC] Acquiring token for system-assigned identity")
                credential = ManagedIdentityCredential()

            logger.info(f"👤 [OGC] PostgreSQL user: {identity_name}")

            # Get access token for PostgreSQL
            token_response = credential.get_token(
                "https://ossrdbms-aad.database.windows.net/.default"
            )
            token = token_response.token

            logger.debug(f"✅ [OGC] Token acquired successfully")

            # Build connection string with token as password
            conn_str = (
                f"host={self.postgis_host} "
                f"port={self.postgis_port} "
                f"dbname={self.postgis_database} "
                f"user={identity_name} "
                f"password={token} "
                f"sslmode=require"
            )

            return conn_str

        except ClientAuthenticationError as e:
            error_msg = (
                f"[OGC] Managed identity token acquisition failed: {e}\n"
                f"Ensure managed identity is assigned to PostgreSQL and user exists."
            )
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg) from e

        except Exception as e:
            error_msg = f"[OGC] Unexpected error during managed identity token acquisition: {e}"
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg) from e

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
