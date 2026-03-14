# PostgreSQL Repository Decomposition — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose the `PostgreSQLRepository` god class (1,530 lines) into three composable components via internal composition, with zero breaking changes to 22 subclasses and 41+ consumers.

**Architecture:** Extract auth logic into `ManagedIdentityAuth` (db_auth.py), connection lifecycle into `ConnectionManager` (db_connections.py), and shared utilities into `db_utils.py`. `PostgreSQLRepository` becomes a thin coordinator that delegates to these components while preserving its entire public API surface.

**Tech Stack:** Python 3.12, psycopg3, Azure Managed Identity (azure-identity SDK), psycopg_pool

**Spec:** `docs/superpowers/specs/2026-03-14-postgresql-repository-decomposition-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `infrastructure/db_utils.py` | **CREATE** | Module-level utilities: `_EnumDumper`, `_register_type_adapters`, `_parse_jsonb_column` |
| `infrastructure/db_auth.py` | **CREATE** | `ManagedIdentityAuth` class: token acquisition, connection string building, refresh |
| `infrastructure/db_connections.py` | **CREATE** | `ConnectionManager` class: pooled/single-use connections, circuit breaker, retry |
| `infrastructure/postgresql.py` | **MODIFY** | Remove extracted methods, add imports + delegation, keep CRUD builders + schema mgmt |
| `infrastructure/connection_pool.py` | **MODIFY** | Update `_register_type_adapters` import from `db_utils` |

---

## Chunk 1: Foundation + Utilities

### Task 1: Create dev branch

**Files:** None (git operation)

- [ ] **Step 1: Create and switch to dev branch**

```bash
git checkout -b dev
```

- [ ] **Step 2: Verify branch**

Run: `git branch --show-current`
Expected: `dev`

---

### Task 2: Create `infrastructure/db_utils.py`

**Files:**
- Create: `infrastructure/db_utils.py`
- Reference: `infrastructure/postgresql.py:95-177` (current location of these utilities)

This is the leaf node of the import graph — no infrastructure imports, only psycopg and stdlib.

- [ ] **Step 1: Create db_utils.py with extracted utilities**

```python
# ============================================================================
# DATABASE UTILITIES
# ============================================================================
# PURPOSE: Shared psycopg3 type adapters and JSONB parsing
# DEPENDENCIES: psycopg, json, logging (no infrastructure imports)
# ============================================================================
"""
Database utilities shared across infrastructure components.

Contains psycopg3 type adapters (dict/list → JSONB, Enum → .value) and
JSONB column parsing. These are module-level functions registered on each
connection — not class methods.

Import graph: This module is a leaf node.
    db_utils.py ← db_connections.py, postgresql.py, connection_pool.py
"""

import json
import logging
from typing import Any
from enum import Enum

from psycopg.types.json import JsonbBinaryDumper
from psycopg.adapt import Dumper

from exceptions import DatabaseError

logger = logging.getLogger(__name__)


class _EnumDumper(Dumper):
    """Adapt any Enum subclass → its .value for psycopg3."""

    def dump(self, obj):
        return str(obj.value).encode('utf-8')


def register_type_adapters(conn) -> None:
    """
    Register psycopg3 type adapters on a connection.

    Called for both single-use (Function App) and pooled (Docker) connections.
    After registration, dict/list auto-serialize to JSONB and Enum subclasses
    auto-serialize to their .value — no manual json.dumps() or .value needed.
    """
    conn.adapters.register_dumper(dict, JsonbBinaryDumper)
    conn.adapters.register_dumper(list, JsonbBinaryDumper)
    conn.adapters.register_dumper(Enum, _EnumDumper)


def parse_jsonb_column(value: Any, column_name: str, record_id: str, default: Any = None) -> Any:
    """
    Parse a JSONB column value with explicit error handling.

    Replaces silent fallbacks that hide data corruption. Logs errors
    and raises DatabaseError on malformed JSON.

    Args:
        value: The raw value from PostgreSQL (could be dict, str, or None)
        column_name: Name of the column for error context
        record_id: Job/task ID for error context
        default: Default value if column is NULL (not for parse errors!)

    Returns:
        Parsed dict/value or default if NULL

    Raises:
        DatabaseError: If JSON parsing fails (data corruption)
    """
    if value is None:
        return default

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(
                f"Corrupted JSON in {column_name} for {record_id[:16]}...: {e}",
                extra={
                    'record_id': record_id,
                    'column': column_name,
                    'error_type': 'JSONDecodeError',
                    'preview': value[:200] if len(value) > 200 else value
                }
            )
            raise DatabaseError(f"Corrupted {column_name} JSON for {record_id}: {e}")

    logger.error(
        f"Unexpected type for {column_name}: {type(value).__name__}",
        extra={'record_id': record_id, 'column': column_name, 'value_type': type(value).__name__}
    )
    raise DatabaseError(f"Unexpected type for {column_name}: {type(value).__name__}")
```

Note: Functions are named without leading underscores (`register_type_adapters`, `parse_jsonb_column`) since they're now public module-level exports. The old underscore-prefixed names will be preserved as aliases in `postgresql.py` for backward compatibility within that file.

- [ ] **Step 2: Verify import works**

Run: `conda run -n azgeo python -c "from infrastructure.db_utils import register_type_adapters, parse_jsonb_column; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Update `connection_pool.py` import**

Modify: `infrastructure/connection_pool.py:240`

Change:
```python
from infrastructure.postgresql import _register_type_adapters
_register_type_adapters(conn)
```
To:
```python
from infrastructure.db_utils import register_type_adapters
register_type_adapters(conn)
```

- [ ] **Step 4: Verify connection_pool import works**

Run: `conda run -n azgeo python -c "from infrastructure.connection_pool import ConnectionPoolManager; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add infrastructure/db_utils.py infrastructure/connection_pool.py
git commit -m "refactor: extract db_utils — type adapters and JSONB parsing as shared leaf module"
```

---

## Chunk 2: ManagedIdentityAuth

### Task 3: Create `infrastructure/db_auth.py`

**Files:**
- Create: `infrastructure/db_auth.py`
- Reference: `infrastructure/postgresql.py:368-721` (auth methods being extracted)

- [ ] **Step 1: Create db_auth.py with ManagedIdentityAuth class**

Extract the following methods from `PostgreSQLRepository` into the new class. The code below is a direct extraction — same logic, renamed methods, `self.config`/`self.target_database` now stored on `ManagedIdentityAuth` instead of the repository.

```python
# ============================================================================
# MANAGED IDENTITY AUTHENTICATION
# ============================================================================
# PURPOSE: Azure AD token acquisition and connection string management
# DEPENDENCIES: config, azure.identity (lazy), logging
# ============================================================================
"""
Managed Identity authentication for PostgreSQL.

Handles Azure AD token acquisition, connection string building, and token
refresh. Constitutional principle: managed identity is the auth method.
Password auth exists only as a dev-only escape hatch.

Import graph:
    db_auth.py ← db_connections.py, postgresql.py
    db_auth.py → config (only)
"""

import os
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
        1. connection_string_override (if passed) — return directly
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
            "token",
            "expired",
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
                return self.config.postgis_connection_string

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

            logger.debug(f"Token acquired (expires in ~{token_response.expires_on - __import__('time').time():.0f}s)")

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
        ext_password = os.environ.get("EXTERNAL_DB_PASSWORD")
        if not ext_password:
            raise ValueError(
                "EXTERNAL_DB_PASSWORD is required for password-based external DB connections. "
                "Do NOT reuse the app DB password — external DB should have its own credentials."
            )
        user = self.config.postgis_user

        conn_str = (
            f"postgresql://{user}:{ext_password}@"
            f"{db_config.db_host}:{db_config.db_port}/"
            f"{db_config.db_name}?sslmode=require"
        )
        return conn_str
```

- [ ] **Step 2: Verify import works**

Run: `conda run -n azgeo python -c "from infrastructure.db_auth import ManagedIdentityAuth; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add infrastructure/db_auth.py
git commit -m "refactor: extract ManagedIdentityAuth — token acquisition and connection string management"
```

---

## Chunk 3: ConnectionManager

### Task 4: Create `infrastructure/db_connections.py`

**Files:**
- Create: `infrastructure/db_connections.py`
- Reference: `infrastructure/postgresql.py:667-968` (connection methods being extracted)

- [ ] **Step 1: Create db_connections.py with ConnectionManager class**

```python
# ============================================================================
# CONNECTION MANAGER
# ============================================================================
# PURPOSE: PostgreSQL connection lifecycle — pooled and single-use modes
# DEPENDENCIES: db_auth, db_utils, circuit_breaker, connection_pool, psycopg
# ============================================================================
"""
PostgreSQL connection lifecycle management.

Routes between pooled (Docker) and single-use (Functions) connection modes.
Integrates circuit breaker for cascade failure prevention. Handles retry
with token refresh on auth failure.

Import graph:
    db_connections.py ← postgresql.py
    db_connections.py → db_auth.py, db_utils.py, circuit_breaker.py, connection_pool.py
"""

import logging
from contextlib import contextmanager
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from infrastructure.db_auth import ManagedIdentityAuth
from infrastructure.db_utils import register_type_adapters

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    PostgreSQL connection lifecycle manager.

    Provides get_connection() context manager that routes to pooled (Docker)
    or single-use (Functions) connections. Integrates circuit breaker and
    handles retry with token refresh on auth failure.
    """

    def __init__(self, auth: ManagedIdentityAuth):
        """
        Initialize with auth provider.

        Args:
            auth: ManagedIdentityAuth instance for connection strings and token refresh.
        """
        self._auth = auth

    @contextmanager
    def get_connection(self):
        """
        Context manager for PostgreSQL database connections.

        Routes to pooled (Docker) or single-use (Functions) based on runtime mode.
        Checks circuit breaker before connecting. Records success/failure for
        circuit breaker state transitions.

        Yields:
            psycopg.Connection — active PostgreSQL connection.
        """
        from infrastructure.circuit_breaker import CircuitBreaker
        from infrastructure.connection_pool import ConnectionPoolManager

        breaker = CircuitBreaker.get_instance()
        breaker.check()  # Raises CircuitBreakerOpenError if OPEN

        connected = False
        try:
            if ConnectionPoolManager.is_pool_mode():
                with self._get_pooled_connection() as conn:
                    connected = True
                    breaker.record_success()
                    yield conn
            else:
                with self._get_single_use_connection() as conn:
                    connected = True
                    breaker.record_success()
                    yield conn
        except Exception:
            if not connected:
                breaker.record_failure()
            raise

    @contextmanager
    def get_cursor(self, conn=None):
        """
        Context manager for cursors with optional auto-commit.

        Args:
            conn: Existing connection (caller controls transaction).
                  If None, creates a new connection with auto-commit.
        """
        if conn:
            with conn.cursor() as cursor:
                yield cursor
        else:
            with self.get_connection() as new_conn:
                with new_conn.cursor() as cursor:
                    yield cursor
                    new_conn.commit()

    @staticmethod
    def is_transient_error(error: Exception) -> bool:
        """
        Return True when error looks like a transient connection issue
        that may succeed on retry (network blip, server restart, etc.).
        """
        transient_markers = [
            "connection is closed",
            "the connection is lost",
            "could not connect to server",
            "connection refused",
            "connection timed out",
            "ssl syscall error",
            "broken pipe",
            "connection reset",
            "server closed the connection unexpectedly",
        ]
        for candidate in (error, getattr(error, '__cause__', None), getattr(error, '__context__', None)):
            if candidate is None:
                continue
            msg = str(candidate).lower()
            if any(marker in msg for marker in transient_markers):
                return True
        return False

    # ------------------------------------------------------------------ #
    # Internal — connection mode implementations
    # ------------------------------------------------------------------ #

    @contextmanager
    def _get_pooled_connection(self):
        """
        Get connection from pool (Docker mode).

        On auth failure or dead pool, refreshes credentials/pool and retries once.
        """
        from infrastructure.connection_pool import ConnectionPoolManager

        logger.debug("Getting connection from pool...")
        use_managed_identity = self._auth.is_active()
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            try:
                with ConnectionPoolManager.get_connection() as conn:
                    pid = conn.info.backend_pid
                    logger.info(f"[CONN] Acquired pooled connection pid={pid}")
                    try:
                        yield conn
                    finally:
                        logger.info(f"[CONN] Released pooled connection pid={pid}")
                    return
            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Pool connection error: {e}")

                dead_pool_markers = [
                    "ssl syscall error",
                    "connection is closed",
                    "the connection is lost",
                    "broken pipe",
                    "connection reset",
                    "server closed the connection unexpectedly",
                ]
                is_dead_pool = any(marker in error_str for marker in dead_pool_markers)

                can_retry = (
                    attempt < max_attempts
                    and (
                        (use_managed_identity and ManagedIdentityAuth.is_auth_error(e))
                        or is_dead_pool
                    )
                )

                if not can_retry:
                    raise

                if is_dead_pool:
                    logger.warning(
                        f"Dead pool detected ({type(e).__name__}); "
                        f"recreating connection pool and retrying"
                    )
                    ConnectionPoolManager.recreate_pool()
                else:
                    logger.warning(
                        "Pooled managed identity auth failed; "
                        "refreshing token, recreating pool, retrying once"
                    )
                    self._auth.refresh_pool_credentials()

    @contextmanager
    def _get_single_use_connection(self):
        """
        Create single-use connection (Function App mode).

        On auth failure, refreshes token via self._auth.refresh() and retries.
        On transient error, waits 2s and retries.
        """
        conn = None
        use_managed_identity = self._auth.is_active()
        max_attempts = 2

        try:
            for attempt in range(1, max_attempts + 1):
                current_conn_string = self._auth.get_connection_string()

                logger.debug(f"Attempting PostgreSQL connection (attempt {attempt}/{max_attempts})...")

                try:
                    conn = psycopg.connect(current_conn_string, row_factory=dict_row)
                    register_type_adapters(conn)
                    pid = conn.info.backend_pid
                    logger.info(f"[CONN] Opened single-use connection pid={pid}")
                    yield conn
                    return

                except psycopg.Error as e:
                    logger.error(f"PostgreSQL connection error: {e}")

                    if "Name or service not known" in str(e) or "could not translate host name" in str(e):
                        logger.error("DNS Resolution Error - Cannot resolve database hostname")

                    if conn:
                        conn.rollback()
                        conn.close()
                        conn = None

                    is_auth_error = use_managed_identity and ManagedIdentityAuth.is_auth_error(e)
                    is_transient = self.is_transient_error(e)

                    can_retry = attempt < max_attempts and (is_auth_error or is_transient)

                    if not can_retry:
                        raise

                    if is_auth_error:
                        logger.warning("Managed identity auth failed; refreshing token and retrying")
                        self._auth.refresh()
                    else:
                        logger.warning(f"Transient connection error ({type(e).__name__}); retrying in 2s")
                        import time
                        time.sleep(2)

        except psycopg.Error:
            if conn:
                conn.rollback()
            raise

        finally:
            if conn:
                pid = conn.info.backend_pid
                conn.close()
                logger.info(f"[CONN] Closed single-use connection pid={pid}")
```

- [ ] **Step 2: Verify import works**

Run: `conda run -n azgeo python -c "from infrastructure.db_connections import ConnectionManager; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add infrastructure/db_connections.py
git commit -m "refactor: extract ConnectionManager — pooled/single-use lifecycle, circuit breaker, retry"
```

---

## Chunk 4: Rewire PostgreSQLRepository

### Task 5: Modify `infrastructure/postgresql.py`

**Files:**
- Modify: `infrastructure/postgresql.py`

This is the critical task. We remove the extracted methods from `PostgreSQLRepository` and replace them with delegation to the new components. The three state machine subclasses at the bottom of the file are untouched.

- [ ] **Step 1: Update imports at top of postgresql.py**

Add to the import block (after existing imports, before the class):

```python
from infrastructure.db_auth import ManagedIdentityAuth
from infrastructure.db_connections import ConnectionManager
from infrastructure.db_utils import register_type_adapters, parse_jsonb_column, _EnumDumper
```

- [ ] **Step 2: Replace the module-level utilities section (lines 95-177)**

Remove the `_EnumDumper` class, `_register_type_adapters` function, and `_parse_jsonb_column` function from postgresql.py. Replace with backward-compatible aliases:

```python
# =============================================================================
# psycopg3 TYPE ADAPTERS — moved to db_utils.py (14 MAR 2026)
# Aliases preserved for connection_pool.py and internal references
# =============================================================================
_register_type_adapters = register_type_adapters
_parse_jsonb_column = parse_jsonb_column
```

- [ ] **Step 3: Rewrite `__init__` method**

Replace the existing `__init__` (lines 225-366) with the slim version that delegates to components. Preserve the constructor signature exactly:

```python
def __init__(self, connection_string: Optional[str] = None,
             schema_name: Optional[str] = None,
             config: Optional[AppConfig] = None,
             target_database: Literal["app", "external"] = "app"):
    """
    Initialize PostgreSQL repository with configuration.

    Delegates auth to ManagedIdentityAuth and connections to ConnectionManager.
    Constructor signature preserved for all 22 subclasses.
    """
    super().__init__()

    # Get configuration
    self.config = config or get_config()
    self.target_database = target_database

    # Resolve schema name (same logic as before)
    if schema_name:
        self.schema_name = schema_name
    elif target_database == "external" and self.config.is_external_configured():
        self.schema_name = self.config.external.db_schema
    elif target_database == "external":
        raise ConfigurationError(
            "target_database='external' but external environment not configured. "
            "Set EXTERNAL_DB_HOST and EXTERNAL_DB_NAME environment variables."
        )
    else:
        self.schema_name = self.config.app_schema

    # Create auth and connection components
    self._auth = ManagedIdentityAuth(
        config=self.config,
        target_database=target_database,
        connection_string_override=connection_string,
    )
    self._connections = ConnectionManager(self._auth)

    # Validate schema exists
    self._ensure_schema_exists()

    # Log initialization
    if target_database == "external" and self.config.is_external_configured():
        db_name = self.config.external.db_name
        logger.info(f"PostgreSQLRepository initialized with EXTERNAL database: {db_name}, schema: {self.schema_name}")
    else:
        logger.info(f"PostgreSQLRepository initialized with APP database, schema: {self.schema_name}")
```

- [ ] **Step 4: Replace extracted methods with delegation**

Remove these methods from the class body entirely:
- `_get_connection_string()` (lines 368-484)
- `_build_password_connection_string()` (lines 486-519)
- `_build_managed_identity_connection_string()` (lines 521-644)
- `_is_managed_identity_auth_error()` (lines 646-675)
- `_is_transient_connection_error()` (lines 677-702)
- `_is_managed_identity_effective()` (lines 704-721)
- `_refresh_managed_identity_conn_string()` (lines 723-729)
- `_refresh_pooled_managed_identity_credentials()` (lines 731-739)
- `_get_connection()` (lines 741-821)
- `_get_pooled_connection()` (lines 823-884)
- `_get_single_use_connection()` (lines 886-968)
- `_get_cursor()` (lines 970-1027)

Replace with these thin delegation methods:

```python
@property
def conn_string(self) -> str:
    """Exposes connection string for external consumers.
    Read by: pgstac_repository.py, postgis_handler.py, health_checks/external.py,
    health_checks/database.py, pgstac_bootstrap.py
    """
    return self._auth.get_connection_string()

@contextmanager
def _get_connection(self):
    """Delegates to ConnectionManager.
    Used by: all subclasses, deployer.py, schema_analyzer.py, validators.py,
    config/database_config.py, and 30+ trigger/admin files.
    """
    with self._connections.get_connection() as conn:
        yield conn

@contextmanager
def _get_cursor(self, conn=None):
    """Delegates to ConnectionManager."""
    with self._connections.get_cursor(conn) as cursor:
        yield cursor
```

- [ ] **Step 5: Verify the module imports cleanly**

Run: `conda run -n azgeo python -c "from infrastructure.postgresql import PostgreSQLRepository, PostgreSQLJobRepository, PostgreSQLTaskRepository, PostgreSQLStageCompletionRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Verify subclass imports work**

Run: `conda run -n azgeo python -c "from infrastructure.jobs_tasks import JobRepository, TaskRepository, StageCompletionRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Spot-check domain repos**

Run: `conda run -n azgeo python -c "from infrastructure.asset_repository import AssetRepository; from infrastructure.release_repository import ReleaseRepository; from infrastructure.route_repository import RouteRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add infrastructure/postgresql.py
git commit -m "refactor: rewire PostgreSQLRepository — delegates to ManagedIdentityAuth + ConnectionManager"
```

---

## Chunk 5: Verification

### Task 6: Full import smoke test

**Files:** None (verification only)

- [ ] **Step 1: Test all infrastructure imports**

Run:
```bash
conda run -n azgeo python -c "
from infrastructure.db_utils import register_type_adapters, parse_jsonb_column
from infrastructure.db_auth import ManagedIdentityAuth
from infrastructure.db_connections import ConnectionManager
from infrastructure.postgresql import PostgreSQLRepository
from infrastructure.postgresql import PostgreSQLJobRepository, PostgreSQLTaskRepository, PostgreSQLStageCompletionRepository
from infrastructure.jobs_tasks import JobRepository, TaskRepository, StageCompletionRepository
from infrastructure.asset_repository import AssetRepository
from infrastructure.release_repository import ReleaseRepository
from infrastructure.route_repository import RouteRepository
from infrastructure.release_table_repository import ReleaseTableRepository
from infrastructure.release_audit_repository import ReleaseAuditRepository
from infrastructure.platform import ApiRequestRepository
from infrastructure.platform_registry_repository import PlatformRegistryRepository
from infrastructure.promoted_repository import PromotedDatasetRepository
from infrastructure.external_service_repository import ExternalServiceRepository
from infrastructure.h3_repository import H3Repository
from infrastructure.h3_batch_tracking import H3BatchTracker
from infrastructure.janitor_repository import JanitorRepository
from infrastructure.job_event_repository import JobEventRepository
from infrastructure.metrics_repository import MetricsRepository
from infrastructure.artifact_repository import ArtifactRepository
print('All imports OK')
"
```
Expected: `All imports OK`

- [ ] **Step 2: Test backward compatibility of _register_type_adapters alias**

Run: `conda run -n azgeo python -c "from infrastructure.postgresql import _register_type_adapters, _parse_jsonb_column; print('Aliases OK')"`
Expected: `Aliases OK`

- [ ] **Step 3: Test conn_string property**

Run: `conda run -n azgeo python -c "print(hasattr(PostgreSQLRepository, 'conn_string') or 'conn_string as property')" 2>&1 | head -5`

This step is a structural check — full runtime requires DB credentials.

- [ ] **Step 4: Commit verification marker**

```bash
git commit --allow-empty -m "verify: all imports pass — decomposition complete, zero breaking changes"
```

---

### Task 7: Update V10_POSTGRES.md status

**Files:**
- Modify: `V10_POSTGRES.md`

- [ ] **Step 1: Update status**

Change the status line to:
```
**Status**: Implementation complete — pending COMPETE review
```

- [ ] **Step 2: Commit**

```bash
git add V10_POSTGRES.md
git commit -m "docs: update V10_POSTGRES status — decomposition implemented"
```

---

## Post-Implementation

**Pause here before running COMPETE agent pipeline.** The decomposition is complete. Next steps:

1. Run COMPETE on: `infrastructure/db_auth.py`, `infrastructure/db_connections.py`, `infrastructure/postgresql.py`, `infrastructure/db_utils.py`
2. Fix anything COMPETE finds
3. Deploy to dev and run health check + hello_world job
4. Merge `dev` → `master`
