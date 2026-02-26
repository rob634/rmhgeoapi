"""
Environment variable validation tests.

Tests regex patterns for POSTGIS_HOST and ENVIRONMENT validators.
"""

import pytest
import os
from unittest.mock import patch

from config.env_validation import (
    ENV_VAR_RULES,
    validate_single_var,
    EnvVarRule,
)


class TestPostgisHostValidation:
    """POSTGIS_HOST must be localhost or Azure FQDN."""

    rule = ENV_VAR_RULES["POSTGIS_HOST"]

    def test_localhost_accepted(self, monkeypatch):
        monkeypatch.setenv("POSTGIS_HOST", "localhost")
        result = validate_single_var("POSTGIS_HOST", self.rule)
        assert result is None  # None = no error

    def test_azure_fqdn_accepted(self, monkeypatch):
        monkeypatch.setenv("POSTGIS_HOST", "myserver.postgres.database.azure.com")
        result = validate_single_var("POSTGIS_HOST", self.rule)
        assert result is None

    def test_127_0_0_1_accepted(self, monkeypatch):
        monkeypatch.setenv("POSTGIS_HOST", "127.0.0.1")
        result = validate_single_var("POSTGIS_HOST", self.rule)
        assert result is None

    def test_empty_string_rejected(self, monkeypatch):
        monkeypatch.setenv("POSTGIS_HOST", "")
        result = validate_single_var("POSTGIS_HOST", self.rule)
        assert result is not None
        assert result.severity == "error"

    def test_spaces_rejected(self, monkeypatch):
        monkeypatch.setenv("POSTGIS_HOST", "  ")
        result = validate_single_var("POSTGIS_HOST", self.rule)
        assert result is not None


class TestEnvironmentValidation:
    """ENVIRONMENT must be one of dev, qa, uat, test, staging, prod."""

    rule = ENV_VAR_RULES["ENVIRONMENT"]

    @pytest.mark.parametrize("value", ["dev", "qa", "uat", "test", "staging", "prod", "production"])
    def test_valid_environments_accepted(self, monkeypatch, value):
        monkeypatch.setenv("ENVIRONMENT", value)
        result = validate_single_var("ENVIRONMENT", self.rule)
        assert result is None

    @pytest.mark.parametrize("value", ["development", "local", ""])
    def test_invalid_environments_rejected(self, monkeypatch, value):
        monkeypatch.setenv("ENVIRONMENT", value)
        result = validate_single_var("ENVIRONMENT", self.rule)
        assert result is not None
