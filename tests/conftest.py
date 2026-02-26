"""
Root conftest.py — sys.path, env vars, shared fixtures.

Sets up the test environment so all production code can be imported
without database connections or Azure credentials.
"""

import os
import sys
import hashlib

import pytest

# Add project root to sys.path so 'core', 'jobs', 'config', etc. are importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(autouse=True, scope="session")
def set_minimal_env_vars():
    """
    Set minimal environment variables to prevent import crashes.

    Many modules read env vars at import time. We provide safe defaults
    so imports succeed without Azure infrastructure.
    """
    defaults = {
        "POSTGIS_HOST": "localhost",
        "POSTGIS_DATABASE": "testdb",
        "POSTGIS_SCHEMA": "geo",
        "APP_SCHEMA": "app",
        "PGSTAC_SCHEMA": "pgstac",
        "H3_SCHEMA": "h3",
        "BRONZE_STORAGE_ACCOUNT": "testbronze",
        "SILVER_STORAGE_ACCOUNT": "testsilver",
        "SERVICE_BUS_FQDN": "test.servicebus.windows.net",
        "APP_MODE": "standalone",
        "ENVIRONMENT": "dev",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


@pytest.fixture
def valid_sha256():
    """Generate a valid 64-char SHA256 hex string for ID fields."""
    return hashlib.sha256(b"test-fixture-seed").hexdigest()


@pytest.fixture
def make_sha256():
    """Factory fixture: generate deterministic SHA256 from any string."""
    def _make(seed: str) -> str:
        return hashlib.sha256(seed.encode()).hexdigest()
    return _make
