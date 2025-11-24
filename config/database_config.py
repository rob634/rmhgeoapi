# ============================================================================
# CLAUDE CONTEXT - DATABASE CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New module - Phase 1 of config.py refactoring (20 NOV 2025)
# PURPOSE: PostgreSQL/PostGIS database configuration with managed identity support
# LAST_REVIEWED: 20 NOV 2025
# EXPORTS: DatabaseConfig, get_postgres_connection_string
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: DatabaseConfig
# DEPENDENCIES: pydantic, os, typing
# SOURCE: Environment variables (POSTGIS_HOST, POSTGIS_USER, POSTGIS_PASSWORD, USE_MANAGED_IDENTITY, etc.)
# SCOPE: Database-specific configuration
# VALIDATION: Pydantic v2 validation
# PATTERNS: Value objects, factory methods
# ENTRY_POINTS: from config import DatabaseConfig, get_postgres_connection_string
# INDEX: DatabaseConfig:45, get_postgres_connection_string:160
# ============================================================================

"""
PostgreSQL/PostGIS Database Configuration

Provides configuration for:
- PostgreSQL connection settings
- Managed identity authentication
- Schema names (geo, app, platform, pgstac, h3)
- Connection pooling
- STAC configuration

This module was extracted from config.py (lines 660-773) as part of the
god object refactoring (20 NOV 2025).
"""

import os
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

class DatabaseConfig(BaseModel):
    """
    PostgreSQL/PostGIS configuration with managed identity support.

    Supports both password-based and Azure Managed Identity authentication.
    """

    # Connection settings
    host: str = Field(
        ...,
        description="PostgreSQL server hostname",
        examples=["rmhpgflex.postgres.database.azure.com"]
    )

    port: int = Field(
        default=5432,
        description="PostgreSQL server port number"
    )

    user: Optional[str] = Field(
        default=None,
        description="""PostgreSQL username for password-based authentication.

        IMPORTANT: Only used for password authentication (local development/troubleshooting).

        Authentication Methods:
        - Managed Identity (Production): User is determined by MANAGED_IDENTITY_NAME
        - Password Auth (Dev/Troubleshooting): Uses this POSTGIS_USER value

        Security Note:
        - Production should use managed identity (passwordless)
        - POSTGIS_USER is for troubleshooting only (no passwords in production)
        """
    )

    password: Optional[str] = Field(
        default=None,
        repr=False,
        description="""PostgreSQL password from POSTGIS_PASSWORD environment variable.

        IMPORTANT: Two access patterns exist for this password:
        1. config.database.password (used by health checks) - via this config system
        2. os.environ.get('POSTGIS_PASSWORD') (used by PostgreSQL adapter) - direct access

        Both patterns access the same POSTGIS_PASSWORD environment variable.
        The direct access pattern was implemented during Key Vault → env var migration.

        For new code: Use config.database.password for consistency with other config values.
        """
    )

    database: str = Field(
        ...,
        description="PostgreSQL database name",
        examples=["geopgflex"]
    )

    # Schema names
    postgis_schema: str = Field(
        default="geo",
        description="PostgreSQL schema name for STAC collections and items"
    )

    app_schema: str = Field(
        default="app",
        description="PostgreSQL schema name for application tables (jobs, tasks, etc.)"
    )

    platform_schema: str = Field(
        default="platform",
        description="PostgreSQL schema name for platform orchestration"
    )

    pgstac_schema: str = Field(
        default="pgstac",
        description="PostgreSQL schema name for pgSTAC (STAC catalog)"
    )

    h3_schema: str = Field(
        default="h3",
        description="PostgreSQL schema name for H3 hexagonal grids"
    )

    # Managed identity settings
    use_managed_identity: bool = Field(
        default=False,
        description="""Enable Azure Managed Identity for passwordless PostgreSQL authentication.

        Purpose:
            Eliminates password management by using Azure AD tokens for database authentication.
            Tokens are automatically acquired and refreshed by Azure SDK.

        Behavior:
            - When True: Uses ManagedIdentityCredential to acquire PostgreSQL access tokens
            - When False: Uses traditional password-based authentication

        Environment Variable: USE_MANAGED_IDENTITY

        Prerequisites:
            1. User-assigned managed identity created in Azure (e.g., 'rmhpgflexadmin')
            2. Identity assigned to the Function App in Azure Portal
            3. PostgreSQL user created matching managed identity name (via pgaadauth_create_principal)
            4. Managed identity granted necessary database permissions

        Local Development:
            - Requires `az login` to use AzureCliCredential
            - Or set password fallback in local.settings.json

        Security Benefits:
            - No passwords in configuration or Key Vault
            - Tokens expire after 1 hour (automatic rotation)
            - All authentication logged in Azure AD audit logs
            - Eliminates credential theft risk

        See: docs_claude/QA_DEPLOYMENT.md for setup guide
        """
    )

    managed_identity_name: Optional[str] = Field(
        default=None,
        description="""Managed identity name for PostgreSQL authentication.

        Purpose:
            Specifies the PostgreSQL user name that matches the Azure managed identity.
            This must exactly match the identity name created in PostgreSQL.

        User-Assigned Identity Pattern (RECOMMENDED):
            Use the same user-assigned identity across multiple apps for easier management:
            - 'rmhpgflexadmin' for read/write/admin access (Function App, etc.)
            - 'rmhpgflexreader' for read-only access (TiTiler, OGC/STAC apps)

        Behavior:
            - If specified: Uses this exact name as PostgreSQL user
            - If None: Defaults to 'rmhpgflexadmin' (user-assigned identity)

        Environment Variable: MANAGED_IDENTITY_NAME

        PostgreSQL Setup:
            The managed identity user must be created in PostgreSQL using:
            SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', false, false);
            GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
            GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
            -- etc. for all required schemas

        Important:
            - Name must match EXACTLY (case-sensitive)
            - Must be a valid PostgreSQL identifier
            - For user-assigned identities: matches the identity's display name in Azure AD
        """
    )

    managed_identity_client_id: Optional[str] = Field(
        default=None,
        description="""Client ID of the user-assigned managed identity for PostgreSQL authentication.

        Purpose:
            When using a user-assigned managed identity (recommended pattern), this specifies
            which identity to use for acquiring Azure AD tokens. This is required because
            multiple user-assigned identities can be attached to a single Function App.

        User-Assigned vs System-Assigned:
            - User-Assigned (RECOMMENDED): Specify client_id to use a specific identity
              that can be shared across multiple apps (e.g., 'rmhpgflexadmin')
            - System-Assigned: Leave client_id as None to use the app's own identity

        Benefits of User-Assigned Identity:
            - Single identity for multiple apps (easier to manage)
            - Identity persists even if app is deleted
            - Can grant permissions before app deployment
            - Cleaner separation of concerns

        Environment Variable: MANAGED_IDENTITY_CLIENT_ID

        How to Find Client ID:
            1. Azure Portal → Managed Identities → rmhpgflexadmin
            2. Copy "Client ID" value (NOT Object ID)
            3. Set as MANAGED_IDENTITY_CLIENT_ID environment variable

        Example:
            MANAGED_IDENTITY_CLIENT_ID=12345678-1234-1234-1234-123456789abc
        """
    )

    # Connection pooling (reserved for future use)
    min_connections: int = Field(
        default=1,
        description="Minimum connections in pool (future)"
    )

    max_connections: int = Field(
        default=20,
        description="Maximum connections in pool (future)"
    )

    connection_timeout_seconds: int = Field(
        default=30,
        description="Connection timeout in seconds"
    )

    @property
    def connection_string(self) -> str:
        """
        Build PostgreSQL connection string.

        NOTE: This property is deprecated for managed identity connections.
        PostgreSQLRepository._get_connection_string() builds the connection
        string dynamically with the correct user and token.

        For password auth only, returns basic connection string.
        """
        if self.use_managed_identity:
            # Managed identity: user is determined by MANAGED_IDENTITY_NAME
            # This connection string is not actually used by PostgreSQLRepository
            return f"host={self.host} port={self.port} dbname={self.database}"
        else:
            # Password auth: requires POSTGIS_USER
            if not self.user:
                raise ValueError("POSTGIS_USER is required for password authentication")
            password_part = f" password={self.password}" if self.password else ""
            return f"host={self.host} port={self.port} dbname={self.database} user={self.user}{password_part}"

    def debug_dict(self) -> dict:
        """Debug output with masked password."""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "database": self.database,
            "password": "***MASKED***" if self.password else None,
            "managed_identity": self.use_managed_identity,
            "managed_identity_name": self.managed_identity_name,
            "managed_identity_client_id": self.managed_identity_client_id[:8] + "..." if self.managed_identity_client_id else None,
            "postgis_schema": self.postgis_schema,
            "app_schema": self.app_schema,
            "platform_schema": self.platform_schema,
            "pgstac_schema": self.pgstac_schema,
            "h3_schema": self.h3_schema
        }

    @classmethod
    def from_environment(cls):
        """Load from environment variables.

        POSTGIS_USER is optional when using managed identity authentication.
        It's only required for password-based authentication (local dev/troubleshooting).
        """
        return cls(
            host=os.environ["POSTGIS_HOST"],
            port=int(os.environ.get("POSTGIS_PORT", "5432")),
            user=os.environ.get("POSTGIS_USER"),  # Optional - only for password auth
            password=os.environ.get("POSTGIS_PASSWORD"),
            database=os.environ["POSTGIS_DATABASE"],
            postgis_schema=os.environ.get("POSTGIS_SCHEMA", "geo"),
            app_schema=os.environ.get("APP_SCHEMA", "app"),
            platform_schema=os.environ.get("PLATFORM_SCHEMA", "platform"),
            pgstac_schema=os.environ.get("PGSTAC_SCHEMA", "pgstac"),
            h3_schema=os.environ.get("H3_SCHEMA", "h3"),
            use_managed_identity=os.environ.get("USE_MANAGED_IDENTITY", "false").lower() == "true",
            managed_identity_name=os.environ.get("MANAGED_IDENTITY_NAME"),
            managed_identity_client_id=os.environ.get("MANAGED_IDENTITY_CLIENT_ID"),
            connection_timeout_seconds=int(os.environ.get("DB_CONNECTION_TIMEOUT", "30"))
        )


def get_postgres_connection_string(config: Optional[DatabaseConfig] = None) -> str:
    """
    Legacy compatibility function for getting PostgreSQL connection string.

    DEPRECATED: Use PostgreSQLRepository directly instead.

    This function exists for backward compatibility during the config.py refactoring.
    After migration is complete, all code should use PostgreSQLRepository which
    handles connection management internally.

    Args:
        config: Optional DatabaseConfig instance. If None, creates from environment.

    Returns:
        PostgreSQL connection string

    Example (OLD - being migrated away from):
        conn_string = get_postgres_connection_string()
        with psycopg.connect(conn_string) as conn:
            # ... direct connection management

    Example (NEW - preferred):
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            # ... repository manages connection
    """
    if config is None:
        # During migration: Create config from environment
        config = DatabaseConfig.from_environment()

    return config.connection_string
