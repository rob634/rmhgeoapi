"""
Unit test fixtures — factory-built models.
"""

import pytest

from tests.factories.model_factories import (
    make_job_record,
    make_task_record,
    make_asset,
    make_asset_release,
    make_task_result,
)


@pytest.fixture
def job_record_data():
    """Return randomized job record data dict."""
    return make_job_record()


@pytest.fixture
def task_record_data(valid_sha256):
    """Return randomized task record data dict."""
    return make_task_record(parent_job_id=valid_sha256)


@pytest.fixture
def asset_data():
    """Return randomized asset data dict."""
    return make_asset()


@pytest.fixture
def release_data():
    """Return randomized asset release data dict."""
    return make_asset_release()


@pytest.fixture
def task_result_data():
    """Return randomized task result data dict."""
    return make_task_result()
