# tests/unit/infrastructure/test_api_repository_credentials.py
"""
Unit tests for APIRepository.from_credential_key() flow.
"""
import os
from unittest.mock import patch

import pytest

from infrastructure.acled_repository import ACLEDRepository
from infrastructure.vault import KeyVaultRepository, VaultAccessError


@pytest.fixture(autouse=True)
def _clear_vault_singletons():
    """Prevent singleton/cache leaks between tests."""
    KeyVaultRepository._instances.clear()
    yield
    KeyVaultRepository._instances.clear()


class TestACLEDFromCredentialKey:
    """ACLEDRepository can be constructed from a credential_key."""

    @patch.dict(os.environ, {"ACLED_USERNAME": "user@test.com", "ACLED_PASSWORD": "secret"})
    def test_from_credential_key_password_auth(self):
        repo = ACLEDRepository.from_credential_key("acled")
        assert repo._username == "user@test.com"
        assert repo._password == "secret"

    def test_from_credential_key_missing_raises(self):
        """No ACLED env vars set — should raise VaultAccessError."""
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
