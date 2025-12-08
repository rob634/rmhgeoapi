"""
PostgreSQL/PostGIS Database Configuration.

Provides configuration for:
    - App Database (DatabaseConfig): Full DDL permissions for app infrastructure
      - jobs, tasks, api_requests tables
      - pgSTAC metadata catalog
      - App-owned geo data (admin0 countries)
      - H3 grids
    - Business Database (BusinessDatabaseConfig): Restricted CRUD for ETL outputs
      - process_vector ETL outputs only
      - Same managed identity, different permissions (NO DROP SCHEMA)

Architecture:
    App Database (geopgflex) - Can nuke/rebuild schemas
    Business Database (ddhgeodb) - Protected from accidental destruction

Exports:
    DatabaseConfig: App database configuration
    BusinessDatabaseConfig: Business database configuration
    get_postgres_connection_string: Connection string factory
"""

import os
from typing import Optional
from pydantic import BaseModel, Field

from .defaults import DatabaseDefaults, AzureDefaults


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
        default=DatabaseDefaults.PORT,
        description="PostgreSQL server port number"
    )

    user: Optional[str] = Field(
        default=None,
        description="""PostgreSQL username for password-based authentication.

        IMPORTANT: Only used for password authentication (local development/troubleshooting).

        Authentication Methods:
        - Managed Identity (Production): User is determined by DB_ADMIN_MANAGED_IDENTITY_NAME
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
        default=DatabaseDefaults.POSTGIS_SCHEMA,
        description="PostgreSQL schema name for STAC collections and items"
    )

    app_schema: str = Field(
        default=DatabaseDefaults.APP_SCHEMA,
        description="PostgreSQL schema name for application tables (jobs, tasks, api_requests, janitor_runs)"
    )

    # NOTE: platform_schema REMOVED (26 NOV 2025)
    # Platform tables (api_requests) are stored in app schema, not a separate platform schema.
    # This eliminates schema sprawl and ensures Platform tables are cleaned with full-rebuild.

    pgstac_schema: str = Field(
        default=DatabaseDefaults.PGSTAC_SCHEMA,
        description="PostgreSQL schema name for pgSTAC (STAC catalog)"
    )

    h3_schema: str = Field(
        default=DatabaseDefaults.H3_SCHEMA,
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

    managed_identity_admin_name: Optional[str] = Field(
        default=AzureDefaults.MANAGED_IDENTITY_NAME,
        description="""Admin managed identity name for PostgreSQL authentication.

        Purpose:
            Specifies the PostgreSQL user name for ALL database operations.
            This single identity is used by ETL jobs, OGC/STAC API, TiTiler, and all apps.
            This must exactly match the identity name created in PostgreSQL.

        Architecture (08 DEC 2025):
            Single admin identity for ALL operations - no separate reader identity.
            This simplifies the architecture and deployment configuration.

        Behavior:
            - If specified via env var: Uses that value
            - If not specified: Uses default 'rmhpgflexadmin' (user-assigned identity)

        Environment Variable: DB_ADMIN_MANAGED_IDENTITY_NAME

        PostgreSQL Setup:
            The managed identity user must be created in PostgreSQL using:
            SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', false, false);
            GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
            GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
            GRANT ALL PRIVILEGES ON SCHEMA pgstac TO rmhpgflexadmin;
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

        Environment Variable: DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID

        How to Find Client ID:
            1. Azure Portal → Managed Identities → rmhpgflexadmin
            2. Copy "Client ID" value (NOT Object ID)
            3. Set as DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID environment variable

        Example:
            DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=12345678-1234-1234-1234-123456789abc
        """
    )

    # NOTE (08 DEC 2025): Reader identity removed - using single admin identity for all operations
    # This simplifies the architecture and eliminates the need for separate reader/writer identities.
    # OGC/STAC API and TiTiler now use the same admin identity as the ETL pipeline.

    # Connection pooling (reserved for future use)
    min_connections: int = Field(
        default=DatabaseDefaults.MIN_CONNECTIONS,
        description="Minimum connections in pool (future)"
    )

    max_connections: int = Field(
        default=DatabaseDefaults.MAX_CONNECTIONS,
        description="Maximum connections in pool (future)"
    )

    connection_timeout_seconds: int = Field(
        default=DatabaseDefaults.CONNECTION_TIMEOUT_SECONDS,
        description="Connection timeout in seconds"
    )

    # Azure Environment Detection (08 DEC 2025)
    # These are set automatically by Azure Functions runtime
    azure_website_name: Optional[str] = Field(
        default=None,
        description="""Azure Function App name (auto-detected from WEBSITE_SITE_NAME).

        This is set automatically by Azure Functions runtime. Used to detect
        if running in Azure environment for system-assigned managed identity fallback.

        Environment Variable: WEBSITE_SITE_NAME (set by Azure, not user-configurable)
        """
    )

    @property
    def is_azure_environment(self) -> bool:
        """Check if running in Azure environment (Function App or App Service)."""
        return self.azure_website_name is not None

    @property
    def effective_identity_name(self) -> str:
        """
        Get the effective identity name for managed identity authentication.

        Priority:
        1. managed_identity_admin_name (explicitly configured)
        2. azure_website_name (for system-assigned identity in Azure)
        3. AzureDefaults.MANAGED_IDENTITY_NAME (fallback)
        """
        if self.managed_identity_admin_name:
            return self.managed_identity_admin_name
        if self.azure_website_name:
            return self.azure_website_name
        return AzureDefaults.MANAGED_IDENTITY_NAME

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
            # Managed identity: user is determined by DB_ADMIN_MANAGED_IDENTITY_NAME
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
            "managed_identity_admin_name": self.managed_identity_admin_name,
            "managed_identity_client_id": self.managed_identity_client_id[:8] + "..." if self.managed_identity_client_id else None,
            "postgis_schema": self.postgis_schema,
            "app_schema": self.app_schema,
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
            port=int(os.environ.get("POSTGIS_PORT", str(DatabaseDefaults.PORT))),
            user=os.environ.get("POSTGIS_USER"),  # Optional - only for password auth
            password=os.environ.get("POSTGIS_PASSWORD"),
            database=os.environ["POSTGIS_DATABASE"],
            postgis_schema=os.environ.get("POSTGIS_SCHEMA", DatabaseDefaults.POSTGIS_SCHEMA),
            app_schema=os.environ.get("APP_SCHEMA", DatabaseDefaults.APP_SCHEMA),
            pgstac_schema=os.environ.get("PGSTAC_SCHEMA", DatabaseDefaults.PGSTAC_SCHEMA),
            h3_schema=os.environ.get("H3_SCHEMA", DatabaseDefaults.H3_SCHEMA),
            use_managed_identity=os.environ.get("USE_MANAGED_IDENTITY", "false").lower() == "true",
            managed_identity_admin_name=os.environ.get("DB_ADMIN_MANAGED_IDENTITY_NAME", AzureDefaults.MANAGED_IDENTITY_NAME),
            managed_identity_client_id=os.environ.get("DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID"),
            connection_timeout_seconds=int(os.environ.get("DB_CONNECTION_TIMEOUT", str(DatabaseDefaults.CONNECTION_TIMEOUT_SECONDS))),
            # Azure environment detection (set automatically by Azure Functions runtime)
            azure_website_name=os.environ.get("WEBSITE_SITE_NAME")
        )


# ============================================================================
# BUSINESS DATABASE CONFIGURATION (29 NOV 2025)
# ============================================================================

class BusinessDatabaseConfig(BaseModel):
    """
    Business data database configuration for ETL pipeline outputs.

    This is a SEPARATE database from the app database, used exclusively for
    process_vector ETL outputs. Uses the SAME managed identity (rmhpgflexadmin)
    but with RESTRICTED permissions - specifically NO DROP SCHEMA.

    Architecture:
        App Database (geopgflex):
            - Full DDL: CREATE/DROP SCHEMA, ALL PRIVILEGES
            - Contains: app, pgstac, geo (app reference), h3 schemas
            - Can be nuked/rebuilt for development

        Business Database (ddhgeodb):
            - Restricted: CREATE TABLE, INSERT, UPDATE, DELETE, SELECT
            - NO DROP SCHEMA permission
            - Contains: geo schema (ETL outputs only)
            - Protected from accidental destruction

    Environment Variables:
        BUSINESS_DB_HOST: PostgreSQL host (defaults to POSTGIS_HOST if not set)
        BUSINESS_DB_PORT: Port (default: 5432)
        BUSINESS_DB_NAME: Database name (default: "geodata")
        BUSINESS_DB_SCHEMA: Schema for ETL outputs (default: "geo")
        BUSINESS_DB_MANAGED_IDENTITY_NAME: Identity name (default: "rmhpgflexadmin")
        BUSINESS_DB_MANAGED_IDENTITY_CLIENT_ID: Client ID (optional, uses DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID if not set)

    Usage:
        from config import get_config
        config = get_config()

        # Check if business database is configured
        if config.business_database and config.business_database.is_configured:
            # Use business database for ETL outputs
            business_config = config.business_database
        else:
            # Fall back to app database geo schema
            business_config = config.database
    """

    # Connection settings
    host: str = Field(
        ...,
        description="PostgreSQL server hostname for business database"
    )

    port: int = Field(
        default=DatabaseDefaults.PORT,
        description="PostgreSQL server port number"
    )

    database: str = Field(
        default="ddhgeodb",
        description="Business database name (separate from app database)"
    )

    db_schema: str = Field(
        default=DatabaseDefaults.POSTGIS_SCHEMA,
        description="Schema for ETL outputs (process_vector results)"
    )

    # Managed identity settings (same identity as app database, different permissions)
    use_managed_identity: bool = Field(
        default=True,
        description="Enable Azure Managed Identity (should match app database setting)"
    )

    managed_identity_admin_name: str = Field(
        default=AzureDefaults.MANAGED_IDENTITY_NAME,
        description="""Admin managed identity name - uses SAME identity as app database.

        The key difference is not the identity, but the PERMISSIONS granted
        to this identity on the business database:
        - App database: Full DDL (CREATE/DROP SCHEMA)
        - Business database: Restricted CRUD (NO DROP SCHEMA)
        """
    )

    managed_identity_client_id: Optional[str] = Field(
        default=None,
        description="Client ID of user-assigned managed identity (optional)"
    )

    # Connection settings
    connection_timeout_seconds: int = Field(
        default=DatabaseDefaults.CONNECTION_TIMEOUT_SECONDS,
        description="Connection timeout in seconds"
    )

    @property
    def is_configured(self) -> bool:
        """
        Check if business database is explicitly configured.

        Returns True if BUSINESS_DB_HOST or BUSINESS_DB_NAME environment
        variables are set. This allows the system to fall back to app
        database when business database is not configured.
        """
        return (
            os.environ.get("BUSINESS_DB_HOST") is not None or
            os.environ.get("BUSINESS_DB_NAME") is not None
        )

    def debug_dict(self) -> dict:
        """Debug output for logging."""
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "db_schema": self.db_schema,
            "use_managed_identity": self.use_managed_identity,
            "managed_identity_admin_name": self.managed_identity_admin_name,
            "managed_identity_client_id": self.managed_identity_client_id[:8] + "..." if self.managed_identity_client_id else None,
            "is_configured": self.is_configured
        }

    @classmethod
    def from_environment(cls) -> "BusinessDatabaseConfig":
        """
        Load BusinessDatabaseConfig from environment variables.

        Falls back to app database values when business database
        environment variables are not set.
        """
        return cls(
            # Host: Use BUSINESS_DB_HOST, fall back to POSTGIS_HOST
            host=os.environ.get("BUSINESS_DB_HOST", os.environ.get("POSTGIS_HOST", "")),
            port=int(os.environ.get("BUSINESS_DB_PORT", str(DatabaseDefaults.PORT))),
            database=os.environ.get("BUSINESS_DB_NAME", "ddhgeodb"),
            db_schema=os.environ.get("BUSINESS_DB_SCHEMA", DatabaseDefaults.POSTGIS_SCHEMA),
            use_managed_identity=os.environ.get(
                "BUSINESS_DB_USE_MANAGED_IDENTITY",
                os.environ.get("USE_MANAGED_IDENTITY", "true")
            ).lower() == "true",
            # managed_identity_admin_name: Use env vars, fall back to AzureDefaults
            managed_identity_admin_name=os.environ.get(
                "BUSINESS_DB_MANAGED_IDENTITY_ADMIN_NAME",
                os.environ.get("DB_ADMIN_MANAGED_IDENTITY_NAME", AzureDefaults.MANAGED_IDENTITY_NAME)
            ),
            managed_identity_client_id=os.environ.get(
                "BUSINESS_DB_MANAGED_IDENTITY_CLIENT_ID",
                os.environ.get("DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID")
            ),
            connection_timeout_seconds=int(os.environ.get("BUSINESS_DB_CONNECTION_TIMEOUT", str(DatabaseDefaults.CONNECTION_TIMEOUT_SECONDS)))
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
