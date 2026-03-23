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


@pytest.fixture(autouse=True)
def _clear_singletons():
    """Prevent singleton/cache leaks between tests."""
    KeyVaultRepository._instances.clear()
    yield
    KeyVaultRepository._instances.clear()


class TestResolveCredentialsKeyVault:
    """When Key Vault IS configured, resolve from vault with env var fallback."""

    def _make_repo_with_mock_client(self, secrets_in_vault: dict):
        """Create a KeyVaultRepository with a mocked SecretClient."""
        repo = KeyVaultRepository(vault_name=None)

        mock_client = MagicMock()
        repo._client = mock_client
        repo._vault_name = "test-vault"

        def get_secret_side_effect(name):
            if name in secrets_in_vault:
                mock_secret = MagicMock()
                mock_secret.value = secrets_in_vault[name]
                return mock_secret
            raise Exception(f"Secret {name} not found")

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

    def test_vault_client_credentials_auth(self):
        repo = self._make_repo_with_mock_client({
            "myapp-client-id": "vault-client-id",
            "myapp-client-secret": "vault-client-secret",
        })
        creds = repo.resolve_credentials("myapp")

        assert creds["auth_type"] == "client_credentials"
        assert creds["client_id"] == "vault-client-id"
        assert creds["client_secret"] == "vault-client-secret"

    @patch.dict(os.environ, {"ACLED_USERNAME": "env-user", "ACLED_PASSWORD": "env-pass"})
    def test_vault_miss_falls_back_to_env(self):
        """If vault is configured but secret not found, fall back to env vars."""
        repo = self._make_repo_with_mock_client({})
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
        a = KeyVaultRepository.instance()
        b = KeyVaultRepository.instance()
        assert a is b

    def test_different_vault_names_different_instances(self):
        a = KeyVaultRepository.instance(vault_name=None)
        b = KeyVaultRepository.instance(vault_name="other-vault")
        assert a is not b


class TestCaching:
    """Resolved credentials are cached with TTL."""

    @patch.dict(os.environ, {"ACLED_USERNAME": "u", "ACLED_PASSWORD": "p"})
    def test_second_resolve_hits_cache_not_env(self):
        """Verify cache is used on second call by patching _resolve_from_env."""
        repo = KeyVaultRepository(vault_name=None)
        creds1 = repo.resolve_credentials("acled")

        with patch.object(repo, "_resolve_from_env") as mock_env:
            creds2 = repo.resolve_credentials("acled")
            mock_env.assert_not_called()
        assert creds1 == creds2

    @patch.dict(os.environ, {"ACLED_USERNAME": "u", "ACLED_PASSWORD": "p"})
    def test_clear_cache_forces_re_resolve(self):
        repo = KeyVaultRepository(vault_name=None)
        repo.resolve_credentials("acled")
        assert repo.clear_cache() >= 1
