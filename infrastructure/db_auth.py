# ============================================================================
# CLAUDE CONTEXT - MANAGED_IDENTITY_AUTH
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Database authentication
# PURPOSE: Azure AD token acquisition and connection string management
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: ManagedIdentityAuth
# DEPENDENCIES: config, azure.identity (lazy), logging
# ============================================================================
"""
Managed Identity authentication for PostgreSQL.

Handles Azure AD token acquisition, connection string building, and token
refresh. Constitutional principle: managed identity is the auth method.
Password auth exists only as a dev-only escape hatch.

Import graph:
    db_auth.py <- db_connections.py, postgresql.py
    db_auth.py -> config (only)
"""

import time
import logging
from typing import Optional

from config import AppConfig, get_config, ExternalEnvironmentConfig
from exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class ManagedIdentityAuth:
    """
    Azure Managed Identity authentication for PostgreSQL connections.

    Acquires Azure AD tokens and builds PostgreSQL connection strings.
    Caches the connection string and supports token refresh for retry loops.

    Auth priority chain:
        1. connection_string_override (if passed) -> return directly
        2. User-assigned managed identity (client_id configured)
        3. System-assigned managed identity (Azure environment detected)
        4. Password fallback (dev-only)
        5. FAIL with clear error
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        target_database: str = "app",
        connection_string_override: Optional[str] = None,
    ):
        """
        Initialize auth with configuration.

        Args:
            config: AppConfig instance. Uses get_config() if not provided.
            target_database: "app" or "external" — determines which env vars to read.
            connection_string_override: If provided, used directly (no token acquisition).
        """
        self.config = config or get_config()
        self.target_database = target_database
        self._override = connection_string_override

        # Resolve external config if needed
        self._external_config: Optional[ExternalEnvironmentConfig] = None
        if target_database == "external":
            if not self.config.is_external_configured():
                raise ConfigurationError(
                    "target_database='external' but external environment not configured. "
                    "Set EXTERNAL_DB_HOST and EXTERNAL_DB_NAME environment variables."
                )
            self._external_config = self.config.external

        # Build and cache connection string
        self._cached_conn_string: Optional[str] = None
        if self._override:
            self._cached_conn_string = self._override
        else:
            self._cached_conn_string = self._build_connection_string_from_config()

    def get_connection_string(self) -> str:
        """Return cached connection string."""
        return self._cached_conn_string

    def refresh(self) -> str:
        """
        Rebuild connection string with fresh Azure AD token.

        Called by ConnectionManager on auth failure during retry loop.
        Updates the cached string so next get_connection_string() returns fresh value.

        Returns:
            Fresh connection string.
        """
        if self._override:
            return self._override
        self._cached_conn_string = self._build_connection_string_from_config()
        return self._cached_conn_string

    def refresh_pool_credentials(self) -> None:
        """
        Refresh Docker pooled PostgreSQL credentials and recreate connection pool.
        """
        from infrastructure.auth import refresh_postgres_token
        from infrastructure.connection_pool import ConnectionPoolManager

        refresh_postgres_token()
        ConnectionPoolManager.recreate_pool()

    def is_active(self) -> bool:
        """
        Return True when effective auth path is managed identity.

        Uses config intent + environment signals to determine auth mode.
        """
        if self.target_database == "external" and self._external_config:
            ext_db = self._external_config
            if ext_db.db_use_managed_identity or ext_db.db_managed_identity_client_id:
                return True

        db_cfg = self.config.database
        return bool(
            db_cfg.use_managed_identity
            or db_cfg.managed_identity_client_id
            or db_cfg.is_azure_environment
        )

    @staticmethod
    def is_auth_error(error: Exception) -> bool:
        """
        Return True when error looks like token/auth failure for PostgreSQL MI auth.
        """
        if error is None:
            return False

        auth_markers = [
            "password authentication failed",
            "invalid password",
            "authentication failed",
            "azure ad token",
            "access token",
            "token is expired",
            "token expired",
            "credential expired",
        ]

        for candidate in (error, getattr(error, '__cause__', None), getattr(error, '__context__', None)):
            if candidate is None:
                continue

            sqlstate = getattr(candidate, 'sqlstate', None)
            if sqlstate in {"28P01", "28000"}:
                return True

            msg = str(candidate).lower()
            if any(marker in msg for marker in auth_markers):
                return True

        return False

    # ------------------------------------------------------------------ #
    # Internal — connection string building
    # ------------------------------------------------------------------ #

    def _build_connection_string_from_config(self) -> str:
        """
        Build PostgreSQL connection string with automatic credential detection.

        Priority:
            1. User-assigned managed identity
            2. System-assigned managed identity
            3. Password (dev-only)
            4. FAIL
        """
        use_external_db = (
            self.target_database == "external" and self._external_config is not None
        )

        if use_external_db:
            db_config = self._external_config
            logger.debug(f"Building connection string for EXTERNAL database: {db_config.db_name}")
        else:
            db_config = None
            logger.debug("Building connection string for APP database")

        # Get credentials from config
        if use_external_db and db_config:
            client_id = db_config.db_managed_identity_client_id
            identity_name = db_config.db_managed_identity_name
        else:
            client_id = self.config.database.managed_identity_client_id
            identity_name = self.config.database.effective_identity_name

        is_azure = self.config.database.is_azure_environment
        password = self.config.postgis_password

        # Priority 1: User-Assigned Managed Identity
        if client_id:
            logger.info(f"[AUTH] Using USER-ASSIGNED managed identity: {identity_name} (client_id: {client_id[:8]}...)")
            return self._build_managed_identity_string(
                client_id=client_id,
                identity_name=identity_name,
                db_config=db_config
            )

        # Priority 2: System-Assigned Managed Identity
        if is_azure:
            logger.info(f"[AUTH] Using SYSTEM-ASSIGNED managed identity: {identity_name}")
            return self._build_managed_identity_string(
                client_id=None,
                identity_name=identity_name,
                db_config=db_config
            )

        # Priority 3: Password Authentication (dev-only)
        if password:
            logger.info("[AUTH] Using PASSWORD authentication (local development mode)")
            if use_external_db and db_config:
                return self._build_external_password_string(db_config)
            else:
                # Append password at point of use — connection_string no longer embeds it
                return f"{self.config.postgis_connection_string} password={password}"

        # Priority 4: FAIL
        error_msg = (
            "NO DATABASE CREDENTIALS FOUND!\n"
            "Please configure one of the following:\n"
            "  1. User-Assigned Identity: Set DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID + DB_ADMIN_MANAGED_IDENTITY_NAME\n"
            "  2. System-Assigned Identity: Deploy to Azure (auto-detected via WEBSITE_SITE_NAME)\n"
            "  3. Password Auth: Set POSTGIS_PASSWORD environment variable\n"
            "\n"
            "Current config state:\n"
            f"  - managed_identity_client_id: {'set' if client_id else 'NOT SET'}\n"
            f"  - is_azure_environment: {is_azure}\n"
            f"  - postgis_password: {'set' if password else 'NOT SET'}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    def _build_managed_identity_string(
        self,
        client_id: Optional[str],
        identity_name: str,
        db_config: Optional[ExternalEnvironmentConfig] = None,
    ) -> str:
        """
        Build connection string using Azure Managed Identity token.
        """
        from azure.identity import ManagedIdentityCredential
        from azure.core.exceptions import ClientAuthenticationError

        if db_config:
            db_host = db_config.db_host
            db_port = db_config.db_port
            db_name = db_config.db_name
        else:
            db_host = self.config.postgis_host
            db_port = self.config.postgis_port
            db_name = self.config.postgis_database

        try:
            if client_id:
                credential = ManagedIdentityCredential(client_id=client_id)
            else:
                credential = ManagedIdentityCredential()

            logger.info(f"PostgreSQL user: {identity_name}, database: {db_name}")

            token_response = credential.get_token(
                "https://ossrdbms-aad.database.windows.net/.default"
            )
            token = token_response.token

            logger.debug(f"Token acquired (expires in ~{token_response.expires_on - time.time():.0f}s)")

            conn_str = (
                f"host={db_host} "
                f"port={db_port} "
                f"dbname={db_name} "
                f"user={identity_name} "
                f"password={token} "
                f"sslmode=require"
            )
            return conn_str

        except ClientAuthenticationError as e:
            error_msg = (
                f"Managed identity token acquisition failed: {e}\n"
                f"Ensure managed identity is assigned to PostgreSQL and user exists in database."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

        except Exception as e:
            error_msg = (
                f"Unexpected error during managed identity token acquisition: {e}\n"
                f"Check Azure AD configuration and network connectivity."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def _build_external_password_string(self, db_config: ExternalEnvironmentConfig) -> str:
        """
        Build password connection string for external database (dev-only).

        SECURITY: Requires EXTERNAL_DB_PASSWORD env var.
        Does NOT reuse the app DB password.
        """
        ext_password = db_config.db_password
        if not ext_password:
            raise ValueError(
                "EXTERNAL_DB_PASSWORD is required for password-based external DB connections. "
                "Set EXTERNAL_DB_PASSWORD env var. Do NOT reuse the app DB password."
            )
        user = self.config.postgis_user

        conn_str = (
            f"postgresql://{user}:{ext_password}@"
            f"{db_config.db_host}:{db_config.db_port}/"
            f"{db_config.db_name}?sslmode=require"
        )
        return conn_str


__all__ = ['ManagedIdentityAuth']
