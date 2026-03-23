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
        self._client = None
        self._credential_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = timedelta(minutes=15)

        if vault_name:
            self._init_vault_client(vault_name)

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

    def resolve_credentials(self, credential_key: str) -> Dict[str, Any]:
        """
        Resolve a logical credential key to a credentials dict.

        Probes in priority order:
            1. api_key
            2. client_credentials
            3. password

        Returns the FIRST complete credential set found.
        """
        cached = self._get_cached(credential_key)
        if cached is not None:
            return cached

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

    def get_secret(self, secret_name: str) -> str:
        """
        Retrieve a single secret from Key Vault.

        Falls back to env var {SECRET_NAME} (dots/hyphens replaced with underscores, uppercased).
        """
        value = self._vault_get(secret_name)
        if value is not None:
            return value

        env_key = secret_name.replace("-", "_").replace(".", "_").upper()
        value = os.environ.get(env_key)
        if value:
            return value

        raise VaultAccessError(
            f"Secret '{secret_name}' not found in vault "
            f"({self._vault_name or 'not configured'}) or env var '{env_key}'."
        )

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

    def _resolve_from_vault(self, key: str) -> Optional[Dict[str, Any]]:
        """Probe Key Vault for credential group."""
        if not self._client:
            return None

        api_key = self._vault_get(f"{key}-api-key")
        if api_key:
            return {"auth_type": "api_key", "api_key": api_key}

        client_id = self._vault_get(f"{key}-client-id")
        client_secret = self._vault_get(f"{key}-client-secret")
        if client_id and client_secret:
            return {
                "auth_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }

        username = self._vault_get(f"{key}-username")
        password = self._vault_get(f"{key}-password")
        if username and password:
            return {"auth_type": "password", "username": username, "password": password}

        return None

    def _resolve_from_env(self, key: str) -> Optional[Dict[str, Any]]:
        """Probe environment variables for credential group."""
        upper = key.upper()

        api_key = os.environ.get(f"{upper}_API_KEY")
        if api_key:
            return {"auth_type": "api_key", "api_key": api_key}

        client_id = os.environ.get(f"{upper}_CLIENT_ID")
        client_secret = os.environ.get(f"{upper}_CLIENT_SECRET")
        if client_id and client_secret:
            return {
                "auth_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }

        username = os.environ.get(f"{upper}_USERNAME")
        password = os.environ.get(f"{upper}_PASSWORD")
        if username and password:
            return {"auth_type": "password", "username": username, "password": password}

        return None

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

    @staticmethod
    def _vault_name_from_config() -> Optional[str]:
        """Read key_vault_name from AppConfig. Returns None if not set."""
        try:
            from config import get_config
            return get_config().key_vault_name
        except Exception:
            return None


__all__ = ["KeyVaultRepository", "VaultAccessError"]
