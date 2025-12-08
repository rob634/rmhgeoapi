"""
OGC Features API configuration.

Standalone configuration management for OGC Features API with environment-based settings.

Exports:
    OGCFeaturesConfig: Pydantic configuration model for OGC Features API settings
    get_ogc_config: Singleton function for accessing configuration instance
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

    # Managed Identity Settings (29 NOV 2025, updated 08 DEC 2025)
    # Single admin identity used for all database operations (ETL, OGC/STAC, TiTiler)
    # This simplifies architecture - no separate reader identity needed
    managed_identity_name: str = Field(
        default_factory=lambda: os.getenv("DB_ADMIN_MANAGED_IDENTITY_NAME", "rmhpgflexadmin"),
        description="PostgreSQL user name matching the Azure managed identity"
    )

    # Managed Identity Client ID (08 DEC 2025 - for config-driven auth)
    managed_identity_client_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID"),
        description="Client ID for user-assigned managed identity"
    )

    # Azure Environment Detection (08 DEC 2025)
    azure_website_name: Optional[str] = Field(
        default_factory=lambda: os.getenv("WEBSITE_SITE_NAME"),
        description="Azure Function App name (auto-detected). Used to detect Azure environment."
    )

    @property
    def is_azure_environment(self) -> bool:
        """Check if running in Azure environment."""
        return self.azure_website_name is not None

    @property
    def effective_identity_name(self) -> str:
        """Get effective identity name with fallback to website name for system-assigned."""
        if self.managed_identity_name:
            return self.managed_identity_name
        if self.azure_website_name:
            return self.azure_website_name
        return "rmhpgflexadmin"  # Default

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

        ARCHITECTURE PRINCIPLE (08 DEC 2025 - Config-Driven):
        All credentials are loaded at config instantiation time.
        This method uses config properties only - no direct os.getenv() calls.

        Authentication Priority:
        1. User-Assigned Managed Identity (if managed_identity_client_id is set)
        2. System-Assigned Managed Identity (if is_azure_environment is True)
        3. Password Authentication (if postgis_password is set)

        Returns:
            PostgreSQL connection string (managed identity or password-based)
        """
        import logging
        logger = logging.getLogger(__name__)

        # Priority 1: User-Assigned Managed Identity
        if self.managed_identity_client_id:
            logger.info(f"🔐 [OGC AUTH] Using USER-ASSIGNED managed identity: {self.managed_identity_name}")
            return self._build_managed_identity_connection_string(
                client_id=self.managed_identity_client_id,
                identity_name=self.managed_identity_name
            )

        # Priority 2: System-Assigned Managed Identity (running in Azure)
        if self.is_azure_environment:
            identity_name = self.effective_identity_name
            logger.info(f"🔐 [OGC AUTH] Using SYSTEM-ASSIGNED managed identity: {identity_name}")
            return self._build_managed_identity_connection_string(
                client_id=None,
                identity_name=identity_name
            )

        # Priority 3: Password Authentication
        if self.postgis_password:
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
            "  1. User-Assigned Identity: Set DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID + DB_ADMIN_MANAGED_IDENTITY_NAME\n"
            "  2. System-Assigned Identity: Deploy to Azure (auto-detected via WEBSITE_SITE_NAME)\n"
            "  3. Password Auth: Set POSTGIS_PASSWORD environment variable"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    def _build_managed_identity_connection_string(
        self,
        client_id: str = None,
        identity_name: str = None  # Required - caller must provide from config
    ) -> str:
        """
        Build PostgreSQL connection string using Azure Managed Identity.

        This method acquires an access token from Azure AD and uses it as
        the password in the PostgreSQL connection string.

        Args:
            client_id: Client ID for user-assigned managed identity.
                      If None, uses system-assigned identity.
            identity_name: PostgreSQL user name matching the managed identity.
                          Required - caller must provide (default in config).

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
