# ============================================================================
# CLAUDE CONTEXT - EXTERNAL ENVIRONMENT CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Configuration - External hosting environment (DB + storage + TiTiler)
# PURPOSE: Bundle all external environment settings into single config class
# LAST_REVIEWED: 13 MAR 2026
# EXPORTS: ExternalEnvironmentConfig
# DEPENDENCIES: pydantic, config.defaults
# ============================================================================
"""
External Environment Configuration.

Configures a distinct external hosting environment — a separate database,
storage account, and TiTiler instance — for serving publicly-cleared data
to external consumers.

The internal (application) database remains the system of record. The external
DB holds selective replicas of the geo and pgstac schemas (only datasets with
public clearance).

Environment Variables:
    EXTERNAL_DB_HOST                        - External database hostname
    EXTERNAL_DB_PORT                        - External database port (default 5432)
    EXTERNAL_DB_NAME                        - External database name
    EXTERNAL_DB_SCHEMA                      - External geo schema name (default "geo")
    EXTERNAL_DB_PGSTAC_SCHEMA               - External pgstac schema name (default "pgstac")
    EXTERNAL_DB_USE_MANAGED_IDENTITY        - Enable managed identity auth (default true)
    EXTERNAL_DB_MANAGED_IDENTITY_NAME       - Managed identity display name
    EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID  - Managed identity client ID
    EXTERNAL_DB_CONNECTION_TIMEOUT          - Connection timeout seconds (default 30)
    EXTERNAL_STORAGE_ACCOUNT                - External storage account name
    EXTERNAL_TITILER_URL                    - External TiTiler base URL

Usage:
    from config import get_config
    config = get_config()

    if config.external and config.external.is_configured:
        # Use external environment for public data
        ext = config.external
        print(f"External DB: {ext.db_host}/{ext.db_name}")
"""

import os
from typing import Optional
from pydantic import BaseModel, Field

from .defaults import ExternalDefaults, AzureDefaults


class ExternalEnvironmentConfig(BaseModel):
    """
    Configuration for external hosting environment (separate DB + storage + TiTiler).

    Bundles all three external components into a single config class.
    Replaces the former PublicDatabaseConfig (deleted 10 MAR 2026).
    """

    # --- Database ---
    db_host: str = Field(
        ...,
        description="External database hostname"
    )

    db_port: int = Field(
        default=ExternalDefaults.DB_PORT,
        description="External database port"
    )

    db_name: str = Field(
        ...,
        description="External database name"
    )

    db_schema: str = Field(
        default=ExternalDefaults.DB_SCHEMA,
        description="External geo schema name"
    )

    pgstac_schema: str = Field(
        default=ExternalDefaults.PGSTAC_SCHEMA,
        description="External pgstac schema name"
    )

    db_use_managed_identity: bool = Field(
        default=True,
        description="Enable Azure Managed Identity for external DB authentication"
    )

    db_managed_identity_name: str = Field(
        default=AzureDefaults.MANAGED_IDENTITY_NAME,
        description="Managed identity display name (PostgreSQL username) for external DB"
    )

    db_managed_identity_client_id: Optional[str] = Field(
        default=None,
        description="Client ID of user-assigned managed identity for external DB"
    )

    db_connection_timeout: int = Field(
        default=ExternalDefaults.CONNECTION_TIMEOUT_SECONDS,
        description="Connection timeout in seconds for external DB"
    )

    # --- Storage ---
    storage_account: Optional[str] = Field(
        default=None,
        description="External storage account name for public blob data"
    )

    # --- TiTiler ---
    titiler_url: Optional[str] = Field(
        default=None,
        description="External TiTiler base URL for public tile serving"
    )

    @property
    def is_configured(self) -> bool:
        """True when at minimum the external DB is configured."""
        return bool(self.db_host and self.db_name)

    @property
    def is_fully_configured(self) -> bool:
        """True when DB + storage + TiTiler are all configured."""
        return (
            self.is_configured and
            bool(self.storage_account) and
            bool(self.titiler_url)
        )

    def debug_dict(self) -> dict:
        """Debug output for logging (masks sensitive values)."""
        return {
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_name": self.db_name,
            "db_schema": self.db_schema,
            "pgstac_schema": self.pgstac_schema,
            "db_use_managed_identity": self.db_use_managed_identity,
            "db_managed_identity_name": self.db_managed_identity_name,
            "db_managed_identity_client_id": (
                self.db_managed_identity_client_id[:8] + "..."
                if self.db_managed_identity_client_id else None
            ),
            "storage_account": self.storage_account,
            "titiler_url": self.titiler_url,
            "is_configured": self.is_configured,
            "is_fully_configured": self.is_fully_configured,
        }

    @classmethod
    def from_environment(cls) -> "ExternalEnvironmentConfig":
        """
        Load ExternalEnvironmentConfig from environment variables.

        SECURITY (13 MAR 2026): No fallbacks to app database MI vars.
        EXTERNAL_DB_MANAGED_IDENTITY_* must be explicitly set when using a
        different UMI for external DB. Silent fallback to app identity is
        dangerous — wrong principal, wrong audit trail, wrong permissions.

        If EXTERNAL_DB_HOST is set (external DB intended) and MI is enabled,
        EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID is required.
        """
        db_host = os.environ.get("EXTERNAL_DB_HOST", "")
        db_name = os.environ.get("EXTERNAL_DB_NAME", "")
        is_configured = bool(db_host and db_name)

        # MI flag: external-specific only, default true (same as app)
        db_use_mi = os.environ.get(
            "EXTERNAL_DB_USE_MANAGED_IDENTITY", "true"
        ).lower() == "true"

        # MI identity: NO fallback to app DB identity vars (13 MAR 2026)
        mi_name = os.environ.get("EXTERNAL_DB_MANAGED_IDENTITY_NAME")
        mi_client_id = os.environ.get("EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID")

        # Validate: if external DB is configured with MI, require identity vars
        if is_configured and db_use_mi and not mi_client_id:
            raise ValueError(
                "EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID is required when external DB "
                "uses managed identity. Set EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID to "
                "the client ID of the external DB's user-assigned managed identity. "
                "Do NOT reuse the app DB identity — external DB should have its own UMI."
            )

        if is_configured and db_use_mi and not mi_name:
            raise ValueError(
                "EXTERNAL_DB_MANAGED_IDENTITY_NAME is required when external DB "
                "uses managed identity. Set EXTERNAL_DB_MANAGED_IDENTITY_NAME to "
                "the PostgreSQL username matching the external DB's UMI."
            )

        return cls(
            # Database
            db_host=db_host,
            db_port=int(os.environ.get(
                "EXTERNAL_DB_PORT",
                str(ExternalDefaults.DB_PORT)
            )),
            db_name=db_name,
            db_schema=os.environ.get(
                "EXTERNAL_DB_SCHEMA",
                ExternalDefaults.DB_SCHEMA
            ),
            pgstac_schema=os.environ.get(
                "EXTERNAL_DB_PGSTAC_SCHEMA",
                ExternalDefaults.PGSTAC_SCHEMA
            ),
            db_use_managed_identity=db_use_mi,
            db_managed_identity_name=mi_name or AzureDefaults.MANAGED_IDENTITY_NAME,
            db_managed_identity_client_id=mi_client_id,
            db_connection_timeout=int(os.environ.get(
                "EXTERNAL_DB_CONNECTION_TIMEOUT",
                str(ExternalDefaults.CONNECTION_TIMEOUT_SECONDS)
            )),
            # Storage
            storage_account=os.environ.get("EXTERNAL_STORAGE_ACCOUNT"),
            # TiTiler
            titiler_url=os.environ.get("EXTERNAL_TITILER_URL"),
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['ExternalEnvironmentConfig']
