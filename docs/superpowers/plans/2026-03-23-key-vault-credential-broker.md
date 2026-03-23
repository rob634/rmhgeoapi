# Key Vault Credential Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-source env var credential management with a Key Vault credential broker that resolves logical credential keys to secrets, falling back to env vars for non-breaking migration.

**Architecture:** Rewrite `infrastructure/vault.py` as a singleton `KeyVaultRepository` with a `resolve_credentials()` method that tries Key Vault first, then falls back to `{KEY}_USERNAME`/`{KEY}_PASSWORD`/`{KEY}_API_KEY` env vars. Add `credential_key` field to `ScheduledDataset`. Wire into `APIRepository` base class so subclasses like `ACLEDRepository` can be constructed from resolved credentials without hardcoding env var names.

**Tech Stack:** `azure-keyvault-secrets` (already in requirements), `azure-identity`, `pydantic`, `psycopg`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `infrastructure/vault.py` | **Rewrite** | `KeyVaultRepository` singleton with `get_secret()`, `resolve_credentials()`, env var fallback |
| `infrastructure/api_repository.py` | **Modify (lines 25-52)** | Add `from_credential_key()` classmethod + `_from_credentials()` abstract hook |
| `infrastructure/acled_repository.py` | **Modify (lines 57-76)** | Add `_from_credentials()` classmethod; keep env var `__init__` for backward compat |
| `core/models/scheduled_dataset.py` | **Modify (line 104)** | Add `credential_key` optional field |
| `infrastructure/scheduled_dataset_repository.py` | **Modify (lines 36-50, 86-110, 262-268)** | Add `credential_key` to column lists, create, update |
| `infrastructure/factory.py` | **Modify (lines 360-378)** | Replace `NotImplementedError` with working factory method |
| `tests/unit/infrastructure/__init__.py` | **Create** | Package init |
| `tests/unit/infrastructure/test_key_vault_repository.py` | **Create** | Unit tests for credential resolution + env var fallback |
| `tests/unit/infrastructure/test_api_repository_credentials.py` | **Create** | Unit tests for `from_credential_key()` flow |

---

### Task 1: Rewrite KeyVaultRepository with env var fallback

**Files:**
- Rewrite: `infrastructure/vault.py`
- Test: `tests/unit/infrastructure/test_key_vault_repository.py`

This is the core of the feature. The new `KeyVaultRepository` is a singleton that:
1. Tries Azure Key Vault if `key_vault_name` is configured
2. Falls back to env vars using convention `{KEY_UPPER}_USERNAME` etc.
3. Caches resolved secrets with TTL
4. Returns a typed credential dict with `auth_type` discriminator

- [ ] **Step 1: Create test file with failing tests**

Create `tests/unit/infrastructure/__init__.py` (empty) and the test file:

```python
# tests/unit/infrastructure/test_key_vault_repository.py
"""
Unit tests for KeyVaultRepository credential resolution.

All tests mock Key Vault and env vars — no Azure credentials needed.
"""
import os
from unittest.mock import patch, MagicMock

import pytest

from infrastructure.vault import KeyVaultRepository, VaultAccessError


class TestResolveCredentialsEnvVarFallback:
    """When Key Vault is NOT configured, resolve from env vars."""

    @patch.dict(os.environ, {"ACLED_USERNAME": "user@test.com", "ACLED_PASSWORD": "secret123"})
    def test_password_auth_from_env(self):
        repo = KeyVaultRepository(vault_name=None)
        creds = repo.resolve_credentials("acled")

        assert creds["auth_type"] == "password"
        assert creds["username"] == "user@test.com"
        assert creds["password"] == "secret123"

    @patch.dict(os.environ, {"IBAT_API_KEY": "key-abc-123"})
    def test_api_key_auth_from_env(self):
        repo = KeyVaultRepository(vault_name=None)
        creds = repo.resolve_credentials("ibat")

        assert creds["auth_type"] == "api_key"
        assert creds["api_key"] == "key-abc-123"

    @patch.dict(os.environ, {
        "RELIEFWEB_CLIENT_ID": "client-1",
        "RELIEFWEB_CLIENT_SECRET": "secret-1",
    })
    def test_client_credentials_from_env(self):
        repo = KeyVaultRepository(vault_name=None)
        creds = repo.resolve_credentials("reliefweb")

        assert creds["auth_type"] == "client_credentials"
        assert creds["client_id"] == "client-1"
        assert creds["client_secret"] == "secret-1"

    def test_missing_credentials_raises(self):
        repo = KeyVaultRepository(vault_name=None)
        with pytest.raises(VaultAccessError, match="No credentials found for 'nonexistent'"):
            repo.resolve_credentials("nonexistent")

    @patch.dict(os.environ, {"ACLED_API_KEY": "key-only"})
    def test_api_key_takes_priority_over_missing_password(self):
        """api_key is probed first — if present, wins even if username is absent."""
        repo = KeyVaultRepository(vault_name=None)
        creds = repo.resolve_credentials("acled")

        assert creds["auth_type"] == "api_key"
        assert creds["api_key"] == "key-only"


class TestResolveCredentialsKeyVault:
    """When Key Vault IS configured, resolve from vault with env var fallback."""

    def _make_repo_with_mock_client(self, secrets_in_vault: dict):
        """Create a KeyVaultRepository with a mocked SecretClient."""
        repo = KeyVaultRepository(vault_name=None)  # no vault

        # Manually inject a mock client to simulate vault being configured
        mock_client = MagicMock()
        repo._client = mock_client
        repo._vault_name = "test-vault"

        def get_secret_side_effect(name):
            if name in secrets_in_vault:
                mock_secret = MagicMock()
                mock_secret.value = secrets_in_vault[name]
                return mock_secret
            from azure.core.exceptions import ResourceNotFoundError
            raise ResourceNotFoundError(f"Secret {name} not found")

        mock_client.get_secret.side_effect = get_secret_side_effect
        return repo

    def test_vault_password_auth(self):
        repo = self._make_repo_with_mock_client({
            "acled-username": "vault-user",
            "acled-password": "vault-pass",
        })
        creds = repo.resolve_credentials("acled")

        assert creds["auth_type"] == "password"
        assert creds["username"] == "vault-user"
        assert creds["password"] == "vault-pass"

    def test_vault_api_key_auth(self):
        repo = self._make_repo_with_mock_client({
            "ibat-api-key": "vault-key-123",
        })
        creds = repo.resolve_credentials("ibat")

        assert creds["auth_type"] == "api_key"
        assert creds["api_key"] == "vault-key-123"

    @patch.dict(os.environ, {"ACLED_USERNAME": "env-user", "ACLED_PASSWORD": "env-pass"})
    def test_vault_miss_falls_back_to_env(self):
        """If vault is configured but secret not found, fall back to env vars."""
        repo = self._make_repo_with_mock_client({})  # empty vault
        creds = repo.resolve_credentials("acled")

        assert creds["auth_type"] == "password"
        assert creds["username"] == "env-user"


class TestHasCredentials:
    """has_credentials() is a non-raising probe for health checks."""

    @patch.dict(os.environ, {"ACLED_USERNAME": "u", "ACLED_PASSWORD": "p"})
    def test_returns_true_when_present(self):
        repo = KeyVaultRepository(vault_name=None)
        assert repo.has_credentials("acled") is True

    def test_returns_false_when_absent(self):
        repo = KeyVaultRepository(vault_name=None)
        assert repo.has_credentials("nonexistent") is False


class TestSingleton:
    """KeyVaultRepository.instance() returns same object for same vault."""

    def test_singleton_returns_same_instance(self):
        KeyVaultRepository._instances.clear()
        a = KeyVaultRepository.instance()
        b = KeyVaultRepository.instance()
        assert a is b

    def test_different_vault_names_different_instances(self):
        KeyVaultRepository._instances.clear()
        a = KeyVaultRepository.instance(vault_name=None)
        b = KeyVaultRepository.instance(vault_name="other-vault")
        assert a is not b


class TestCaching:
    """Resolved credentials are cached with TTL."""

    @patch.dict(os.environ, {"ACLED_USERNAME": "u", "ACLED_PASSWORD": "p"})
    def test_second_resolve_uses_cache(self):
        repo = KeyVaultRepository(vault_name=None)
        creds1 = repo.resolve_credentials("acled")
        creds2 = repo.resolve_credentials("acled")
        assert creds1 == creds2

    @patch.dict(os.environ, {"ACLED_USERNAME": "u", "ACLED_PASSWORD": "p"})
    def test_clear_cache_forces_re_resolve(self):
        repo = KeyVaultRepository(vault_name=None)
        repo.resolve_credentials("acled")
        assert repo.clear_cache() >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/infrastructure/test_key_vault_repository.py -v 2>&1 | head -40`

Expected: FAIL — `KeyVaultRepository` constructor signature doesn't match, `resolve_credentials` doesn't exist.

- [ ] **Step 3: Rewrite infrastructure/vault.py**

```python
# ============================================================================
# CLAUDE CONTEXT - KEY VAULT CREDENTIAL BROKER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Infrastructure - Credential resolution via Key Vault + env var fallback
# PURPOSE: Resolve logical credential keys to actual secrets. Try Key Vault
#          first (if configured), fall back to env vars by naming convention.
# LAST_REVIEWED: 23 MAR 2026
# EXPORTS: KeyVaultRepository, VaultAccessError
# DEPENDENCIES: azure-keyvault-secrets, azure-identity, os, logging
# ============================================================================
"""
KeyVaultRepository — credential broker for external API sources.

Resolves a logical credential key (e.g. "acled") to actual credentials
using a two-tier lookup:

    1. Azure Key Vault (if vault_name is configured):
       Probes {key}-api-key, {key}-client-id/{key}-client-secret,
       {key}-username/{key}-password in priority order.

    2. Environment variable fallback (always available):
       Probes {KEY}_API_KEY, {KEY}_CLIENT_ID/{KEY}_CLIENT_SECRET,
       {KEY}_USERNAME/{KEY}_PASSWORD using the same priority order.

Returns a dict with an `auth_type` discriminator:
    {"auth_type": "api_key",            "api_key": "..."}
    {"auth_type": "client_credentials", "client_id": "...", "client_secret": "..."}
    {"auth_type": "password",           "username": "...", "password": "..."}

Singleton per vault name. TTL-cached to avoid per-request vault/env lookups.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VaultAccessError(Exception):
    """Raised when credentials cannot be resolved from any source."""


class KeyVaultRepository:
    """
    Credential broker: Key Vault with env var fallback.

    Singleton per vault_name (None = env-var-only mode).
    """

    _instances: Dict[Optional[str], "KeyVaultRepository"] = {}

    def __init__(self, vault_name: Optional[str] = None) -> None:
        self._vault_name: Optional[str] = vault_name
        self._client = None  # lazy — only created when vault_name is set
        self._credential_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = timedelta(minutes=15)

        if vault_name:
            self._init_vault_client(vault_name)

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls, vault_name: Optional[str] = "_default_") -> "KeyVaultRepository":
        """
        Return singleton for the given vault_name.

        vault_name="_default_" reads config.key_vault_name (may be None).
        vault_name=None forces env-var-only mode.
        """
        if vault_name == "_default_":
            vault_name = cls._vault_name_from_config()

        if vault_name not in cls._instances:
            cls._instances[vault_name] = cls(vault_name=vault_name)
            logger.info(
                "KeyVaultRepository singleton created (vault=%s)",
                vault_name or "env-var-only",
            )
        return cls._instances[vault_name]

    # ------------------------------------------------------------------
    # Public: resolve credentials
    # ------------------------------------------------------------------

    def resolve_credentials(self, credential_key: str) -> Dict[str, Any]:
        """
        Resolve a logical credential key to a credentials dict.

        Probes in priority order:
            1. api_key      — single secret
            2. client_credentials — client_id + client_secret pair
            3. password     — username + password pair

        Returns the FIRST complete credential set found.

        Args:
            credential_key: Logical name, e.g. "acled", "ibat"

        Returns:
            Dict with "auth_type" plus credential fields.

        Raises:
            VaultAccessError: If no valid credential set is found.
        """
        cached = self._get_cached(credential_key)
        if cached is not None:
            return cached

        # Try Key Vault first (if configured), then env vars
        creds = self._resolve_from_vault(credential_key)
        if creds is None:
            creds = self._resolve_from_env(credential_key)

        if creds is None:
            raise VaultAccessError(
                f"No credentials found for '{credential_key}'. "
                f"Checked Key Vault ({self._vault_name or 'not configured'}) "
                f"and env vars ({credential_key.upper()}_API_KEY / _USERNAME / _PASSWORD / "
                f"_CLIENT_ID / _CLIENT_SECRET)."
            )

        self._cache_credentials(credential_key, creds)
        return creds

    def has_credentials(self, credential_key: str) -> bool:
        """Non-raising probe. Returns True if credentials can be resolved."""
        try:
            self.resolve_credentials(credential_key)
            return True
        except VaultAccessError:
            return False

    # ------------------------------------------------------------------
    # Public: raw secret access (for non-credential use cases)
    # ------------------------------------------------------------------

    def get_secret(self, secret_name: str) -> str:
        """
        Retrieve a single secret from Key Vault.

        Falls back to env var {SECRET_NAME} (dots/hyphens replaced with underscores, uppercased).

        Raises:
            VaultAccessError: If secret not found in vault or env.
        """
        # Try vault
        value = self._vault_get(secret_name)
        if value is not None:
            return value

        # Env var fallback: acled-password -> ACLED_PASSWORD
        env_key = secret_name.replace("-", "_").replace(".", "_").upper()
        value = os.environ.get(env_key)
        if value:
            return value

        raise VaultAccessError(
            f"Secret '{secret_name}' not found in vault "
            f"({self._vault_name or 'not configured'}) or env var '{env_key}'."
        )

    # ------------------------------------------------------------------
    # Public: cache management
    # ------------------------------------------------------------------

    def clear_cache(self, credential_key: Optional[str] = None) -> int:
        """Clear all or specific cached credentials. Returns count cleared."""
        if credential_key:
            removed = 1 if self._credential_cache.pop(credential_key, None) else 0
        else:
            removed = len(self._credential_cache)
            self._credential_cache.clear()
        logger.info("KeyVaultRepository cache cleared: %d entries", removed)
        return removed

    def get_info(self) -> Dict[str, Any]:
        """Diagnostic info for health endpoints."""
        return {
            "vault_name": self._vault_name,
            "vault_configured": self._client is not None,
            "cache_ttl_minutes": self._cache_ttl.total_seconds() / 60,
            "cached_keys": list(self._credential_cache.keys()),
        }

    # ------------------------------------------------------------------
    # Internal: Key Vault client
    # ------------------------------------------------------------------

    def _init_vault_client(self, vault_name: str) -> None:
        """Lazily create the Azure SecretClient."""
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            vault_url = f"https://{vault_name}.vault.azure.net/"
            credential = DefaultAzureCredential()
            self._client = SecretClient(vault_url=vault_url, credential=credential)
            logger.info("Key Vault client initialised for %s", vault_name)
        except Exception as exc:
            logger.warning(
                "Key Vault client init failed for %s: %s — will use env var fallback only",
                vault_name, exc,
            )
            self._client = None

    def _vault_get(self, secret_name: str) -> Optional[str]:
        """Try to fetch a single secret from Key Vault. Returns None on miss."""
        if not self._client:
            return None
        try:
            secret = self._client.get_secret(secret_name)
            return secret.value if secret.value else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal: resolution strategies
    # ------------------------------------------------------------------

    def _resolve_from_vault(self, key: str) -> Optional[Dict[str, Any]]:
        """Probe Key Vault for credential group. Returns None if vault not configured or miss."""
        if not self._client:
            return None

        # 1. API key
        api_key = self._vault_get(f"{key}-api-key")
        if api_key:
            return {"auth_type": "api_key", "api_key": api_key}

        # 2. Client credentials
        client_id = self._vault_get(f"{key}-client-id")
        client_secret = self._vault_get(f"{key}-client-secret")
        if client_id and client_secret:
            return {
                "auth_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }

        # 3. Username/password
        username = self._vault_get(f"{key}-username")
        password = self._vault_get(f"{key}-password")
        if username and password:
            return {"auth_type": "password", "username": username, "password": password}

        return None

    def _resolve_from_env(self, key: str) -> Optional[Dict[str, Any]]:
        """Probe environment variables for credential group."""
        upper = key.upper()

        # 1. API key
        api_key = os.environ.get(f"{upper}_API_KEY")
        if api_key:
            return {"auth_type": "api_key", "api_key": api_key}

        # 2. Client credentials
        client_id = os.environ.get(f"{upper}_CLIENT_ID")
        client_secret = os.environ.get(f"{upper}_CLIENT_SECRET")
        if client_id and client_secret:
            return {
                "auth_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }

        # 3. Username/password
        username = os.environ.get(f"{upper}_USERNAME")
        password = os.environ.get(f"{upper}_PASSWORD")
        if username and password:
            return {"auth_type": "password", "username": username, "password": password}

        return None

    # ------------------------------------------------------------------
    # Internal: caching
    # ------------------------------------------------------------------

    def _get_cached(self, credential_key: str) -> Optional[Dict[str, Any]]:
        """Return cached credentials if not expired."""
        entry = self._credential_cache.get(credential_key)
        if entry is None:
            return None
        if datetime.now(timezone.utc) > entry["expires_at"]:
            del self._credential_cache[credential_key]
            return None
        return entry["credentials"]

    def _cache_credentials(self, credential_key: str, creds: Dict[str, Any]) -> None:
        """Cache resolved credentials with TTL."""
        self._credential_cache[credential_key] = {
            "credentials": creds,
            "expires_at": datetime.now(timezone.utc) + self._cache_ttl,
        }

    # ------------------------------------------------------------------
    # Internal: config helper
    # ------------------------------------------------------------------

    @staticmethod
    def _vault_name_from_config() -> Optional[str]:
        """Read key_vault_name from AppConfig. Returns None if not set."""
        try:
            from config import get_config
            return get_config().key_vault_name
        except Exception:
            return None


__all__ = ["KeyVaultRepository", "VaultAccessError"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/infrastructure/test_key_vault_repository.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add infrastructure/vault.py tests/unit/infrastructure/
git commit -m "feat: rewrite KeyVaultRepository as credential broker with env var fallback"
```

---

### Task 2: Add credential_key field to ScheduledDataset model

**Files:**
- Modify: `core/models/scheduled_dataset.py:96-104`
- Test: Run existing model tests to verify no regressions

- [ ] **Step 1: Add credential_key field after rebuild_strategy (line 104)**

Insert after line 104 (`description="How sync updates the table: append | truncate_reload",`):

```python
    credential_key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Key Vault credential group name (e.g. 'acled'). "
                    "Resolves to secrets via KeyVaultRepository.resolve_credentials().",
    )
```

- [ ] **Step 2: Verify model instantiation still works**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from core.models.scheduled_dataset import ScheduledDataset; d = ScheduledDataset(dataset_id='test', table_name='t'); print(d.credential_key); d2 = ScheduledDataset(dataset_id='test2', table_name='t2', credential_key='acled'); print(d2.credential_key)"`

Expected:
```
None
acled
```

- [ ] **Step 3: Commit**

```bash
git add core/models/scheduled_dataset.py
git commit -m "feat: add credential_key field to ScheduledDataset model"
```

---

### Task 3: Add credential_key to ScheduledDatasetRepository

**Files:**
- Modify: `infrastructure/scheduled_dataset_repository.py:36-50` (column list), `86-110` (create SQL), `262-268` (update allowed fields)

- [ ] **Step 1: Add credential_key to _ALL_COLUMNS tuple (line 43, after "rebuild_strategy")**

```python
_ALL_COLUMNS = (
    "dataset_id",
    "table_name",
    "table_schema",
    "schedule_id",
    "description",
    "source_type",
    "column_schema",
    "rebuild_strategy",
    "credential_key",
    "row_count",
    "last_sync_at",
    "last_sync_run_id",
    "created_at",
    "updated_at",
)
```

- [ ] **Step 2: Add credential_key parameter to create() method**

In the `create()` method signature (line 69), add `credential_key: Optional[str] = None` parameter.

Update the INSERT SQL (line 86) to include `credential_key` in the column list and `%s` in VALUES.

Update the params tuple (line 101) to include `credential_key` after `rebuild_strategy`.

The updated create method signature and SQL:

```python
    def create(
        self,
        dataset_id: str,
        table_name: str,
        table_schema: str = "geo",
        schedule_id: Optional[str] = None,
        description: Optional[str] = None,
        source_type: str = "api",
        column_schema: Optional[dict] = None,
        rebuild_strategy: str = "append",
        credential_key: Optional[str] = None,
    ) -> dict:
```

Insert SQL becomes:
```python
        insert_sql = sql.SQL(
            "INSERT INTO {schema}.{table} ("
            "dataset_id, table_name, table_schema, schedule_id, description, "
            "source_type, column_schema, rebuild_strategy, credential_key, "
            "row_count, last_sync_at, last_sync_run_id, created_at, updated_at"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, "
            "0, NULL, NULL, NOW(), NOW()"
            ") RETURNING {cols}"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
            cols=_SELECT_COLS,
        )

        params = (
            dataset_id,
            table_name,
            table_schema,
            schedule_id,
            description,
            source_type,
            json.dumps(column_schema or {}),
            rebuild_strategy,
            credential_key,
        )
```

- [ ] **Step 3: Add credential_key to update() _ALLOWED set (line 262)**

```python
        _ALLOWED = frozenset({
            "description",
            "source_type",
            "column_schema",
            "rebuild_strategy",
            "schedule_id",
            "credential_key",
        })
```

- [ ] **Step 4: Verify the column addition won't break the DB**

This is an additive column change. The `action=ensure` endpoint will handle it. No migration script needed.

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from infrastructure.scheduled_dataset_repository import _ALL_COLUMNS; print(len(_ALL_COLUMNS), _ALL_COLUMNS)"`

Expected: 14 columns listed including `credential_key`.

- [ ] **Step 5: Commit**

```bash
git add infrastructure/scheduled_dataset_repository.py
git commit -m "feat: add credential_key to ScheduledDatasetRepository CRUD"
```

---

### Task 4: Add from_credential_key to APIRepository base

**Files:**
- Modify: `infrastructure/api_repository.py:25-52`
- Modify: `infrastructure/acled_repository.py:57-76`
- Test: `tests/unit/infrastructure/test_api_repository_credentials.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/infrastructure/test_api_repository_credentials.py
"""
Unit tests for APIRepository.from_credential_key() flow.
"""
import os
from unittest.mock import patch

import pytest

from infrastructure.acled_repository import ACLEDRepository
from infrastructure.vault import VaultAccessError


class TestACLEDFromCredentialKey:
    """ACLEDRepository can be constructed from a credential_key."""

    @patch.dict(os.environ, {"ACLED_USERNAME": "user@test.com", "ACLED_PASSWORD": "secret"})
    def test_from_credential_key_password_auth(self):
        repo = ACLEDRepository.from_credential_key("acled")
        assert repo._username == "user@test.com"
        assert repo._password == "secret"

    @patch.dict(os.environ, {}, clear=True)
    def test_from_credential_key_missing_raises(self):
        # Clear ACLED vars to force failure
        env = {k: v for k, v in os.environ.items() if not k.startswith("ACLED")}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(VaultAccessError):
                ACLEDRepository.from_credential_key("acled")

    @patch.dict(os.environ, {"ACLED_API_KEY": "some-key"})
    def test_from_credential_key_wrong_auth_type_raises(self):
        """ACLED requires password auth, not api_key."""
        from exceptions import ContractViolationError
        with pytest.raises(ContractViolationError):
            ACLEDRepository.from_credential_key("acled")


class TestACLEDEnvVarStillWorks:
    """Existing ACLEDRepository() constructor still reads env vars directly."""

    @patch.dict(os.environ, {"ACLED_USERNAME": "u", "ACLED_PASSWORD": "p"})
    def test_legacy_constructor(self):
        repo = ACLEDRepository()
        assert repo._username == "u"
        assert repo._password == "p"

    def test_legacy_constructor_missing_raises_value_error(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("ACLED")}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError):
                ACLEDRepository()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/infrastructure/test_api_repository_credentials.py -v 2>&1 | head -30`

Expected: FAIL — `from_credential_key` doesn't exist.

- [ ] **Step 3: Add from_credential_key to APIRepository base class**

In `infrastructure/api_repository.py`, add after the `get_auth_headers()` abstract method (after line 73):

```python
    # ------------------------------------------------------------------
    # Credential-key construction
    # ------------------------------------------------------------------

    @classmethod
    def from_credential_key(cls, credential_key: str, **kwargs) -> "APIRepository":
        """
        Construct an authenticated APIRepository from a logical credential key.

        Resolves credentials via KeyVaultRepository (Key Vault + env var fallback),
        then delegates to the subclass _from_credentials() hook.

        Args:
            credential_key: Logical name (e.g. "acled", "ibat").

        Returns:
            Fully constructed subclass instance.

        Raises:
            VaultAccessError: If credentials cannot be resolved.
            ContractViolationError: If auth_type is incompatible with subclass.
        """
        from infrastructure.vault import KeyVaultRepository

        vault = KeyVaultRepository.instance()
        creds = vault.resolve_credentials(credential_key)
        return cls._from_credentials(creds, **kwargs)

    @classmethod
    def _from_credentials(cls, creds: dict, **kwargs) -> "APIRepository":
        """
        Subclass hook: build instance from a resolved credential dict.

        Override in subclasses. Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{cls.__name__} must implement _from_credentials() "
            f"to support from_credential_key() construction."
        )
```

- [ ] **Step 4: Add _from_credentials to ACLEDRepository**

In `infrastructure/acled_repository.py`, add after the `__init__` method (after line 87):

```python
    @classmethod
    def _from_credentials(cls, creds: dict, **kwargs) -> "ACLEDRepository":
        """
        Build ACLEDRepository from resolved credential dict.

        Requires auth_type == "password" (OAuth 2.0 password grant).
        """
        from exceptions import ContractViolationError

        if creds["auth_type"] != "password":
            raise ContractViolationError(
                f"ACLEDRepository requires auth_type='password', got '{creds['auth_type']}'. "
                f"ACLED uses OAuth 2.0 password grant — store credentials as "
                f"{{key}}-username and {{key}}-password."
            )

        instance = cls.__new__(cls)
        super(ACLEDRepository, instance).__init__(
            base_url=cls.BASE_URL, timeout=60, max_retries=3,
        )
        instance._username = creds["username"]
        instance._password = creds["password"]
        instance._access_token = None
        instance._refresh_token_value = None
        instance._token_expiry = None

        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        logger.info("ACLEDRepository initialised via credential_key for user=%s", creds["username"])
        return instance
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/infrastructure/test_api_repository_credentials.py -v`

Expected: All tests PASS.

- [ ] **Step 6: Run ALL tests to verify no regressions**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/ -v --tb=short 2>&1 | tail -20`

Expected: All existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add infrastructure/api_repository.py infrastructure/acled_repository.py tests/unit/infrastructure/test_api_repository_credentials.py
git commit -m "feat: add from_credential_key() to APIRepository + ACLEDRepository"
```

---

### Task 5: Wire factory method and clean up

**Files:**
- Modify: `infrastructure/factory.py:360-378`

- [ ] **Step 1: Replace NotImplementedError with working factory method**

Replace lines 360-378 of `infrastructure/factory.py`:

```python
    @staticmethod
    def create_key_vault_repository(
        vault_name: Optional[str] = None,
    ) -> 'KeyVaultRepository':
        """
        Create Key Vault credential broker (singleton).

        If vault_name is None, reads config.key_vault_name. If that is also
        None, operates in env-var-only mode (no Azure Key Vault calls).

        Returns:
            KeyVaultRepository singleton instance
        """
        from .vault import KeyVaultRepository

        return KeyVaultRepository.instance(vault_name=vault_name)
```

- [ ] **Step 2: Verify factory works**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from infrastructure.factory import RepositoryFactory; r = RepositoryFactory.create_key_vault_repository(); print(r.get_info())"`

Expected: Dict with `vault_name: None`, `vault_configured: False`, `cached_keys: []`.

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/ -v --tb=short 2>&1 | tail -20`

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add infrastructure/factory.py
git commit -m "feat: wire create_key_vault_repository() in RepositoryFactory"
```

---

## Summary of non-breaking changes

| What changed | Breaking? | Why not |
|---|---|---|
| `vault.py` rewritten | No | Old `VaultRepository` was behind `NotImplementedError` — nobody could call it |
| `ScheduledDataset.credential_key` added | No | Optional field with `default=None` |
| `ScheduledDatasetRepository` gains `credential_key` column | No | Additive column, `action=ensure` handles it |
| `APIRepository.from_credential_key()` added | No | New classmethod, existing constructors unchanged |
| `ACLEDRepository._from_credentials()` added | No | New classmethod, `__init__` still reads env vars |
| `RepositoryFactory.create_key_vault_repository()` | No | Replaces `NotImplementedError` stub |

After deploying, run `action=ensure` to create the `credential_key` column in `app.scheduled_datasets`.

## Post-deploy: populate Key Vault (future, not in this plan)

When you're ready to move secrets to Key Vault:

```bash
az keyvault secret set --vault-name rmhazurevault --name acled-username --value "user@acled.com"
az keyvault secret set --vault-name rmhazurevault --name acled-password --value "the-password"
az functionapp config appsettings set --name rmhazuregeoapi --resource-group rmhazure_rg --settings KEY_VAULT=rmhazurevault
```

Then remove `ACLED_USERNAME`/`ACLED_PASSWORD` from app settings. The `resolve_credentials("acled")` call automatically switches from env vars to Key Vault — zero code change.
