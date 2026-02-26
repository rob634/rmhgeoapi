"""
Config test fixtures — clean environment via monkeypatch.
"""

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """Remove all env vars that config modules might read, for isolation."""
    env_vars_to_clear = [
        "POSTGIS_HOST", "POSTGIS_DATABASE", "POSTGIS_SCHEMA",
        "APP_SCHEMA", "PGSTAC_SCHEMA", "H3_SCHEMA",
        "BRONZE_STORAGE_ACCOUNT", "SILVER_STORAGE_ACCOUNT",
        "SERVICE_BUS_FQDN", "ENVIRONMENT", "APP_MODE",
        "PLATFORM_PRIMARY_CLIENT", "PLATFORM_WEBHOOK_ENABLED",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch
