"""
PlatformConfig and generate_platform_request_id tests.

Property assertions on IDs: 32-char hex, deterministic, collision-resistant.
"""

import pytest
import re

from config.platform_config import PlatformConfig, generate_platform_request_id


class TestGeneratePlatformRequestId:

    def test_request_id_is_32_char_hex(self):
        result = generate_platform_request_id("dataset-1", "resource-1", "v1")
        assert len(result) == 32
        assert re.match(r"^[0-9a-f]{32}$", result)

    def test_request_id_deterministic(self):
        a = generate_platform_request_id("ds", "rs", "v1")
        b = generate_platform_request_id("ds", "rs", "v1")
        assert a == b

    def test_draft_differs_from_versioned(self):
        draft = generate_platform_request_id("ds", "rs", None)
        versioned = generate_platform_request_id("ds", "rs", "v1")
        assert draft != versioned

    def test_different_datasets_different_ids(self):
        id1 = generate_platform_request_id("ds-a", "rs", "v1")
        id2 = generate_platform_request_id("ds-b", "rs", "v1")
        assert id1 != id2

    def test_different_resources_different_ids(self):
        id1 = generate_platform_request_id("ds", "rs-a", "v1")
        id2 = generate_platform_request_id("ds", "rs-b", "v1")
        assert id1 != id2

    def test_custom_length(self):
        result = generate_platform_request_id("ds", "rs", "v1", length=16)
        assert len(result) == 16

    def test_separator_prevents_collisions(self):
        id1 = generate_platform_request_id("a", "bc", "d")
        id2 = generate_platform_request_id("ab", "c", "d")
        assert id1 != id2


class TestPlatformConfigHelpers:

    @pytest.fixture
    def config(self):
        return PlatformConfig()

    def test_vector_table_uses_ordinal(self, config):
        name = config.generate_vector_table_name("floods", "jakarta", version_ordinal=1)
        assert "ord1" in name

    def test_vector_table_uses_version_id(self, config):
        name = config.generate_vector_table_name("floods", "jakarta", version_id="v2")
        assert "v2" in name

    def test_vector_table_draft_fallback(self, config):
        name = config.generate_vector_table_name("floods", "jakarta")
        assert "draft" in name

    def test_raster_output_folder_uses_version(self, config):
        path = config.generate_raster_output_folder("imagery", "site-a", "v1.0")
        assert "v1.0" in path

    def test_raster_output_folder_draft_fallback(self, config):
        path = config.generate_raster_output_folder("imagery", "site-a")
        assert "draft" in path

    def test_different_ordinals_different_paths(self, config):
        name1 = config.generate_vector_table_name("ds", "rs", version_ordinal=1)
        name2 = config.generate_vector_table_name("ds", "rs", version_ordinal=2)
        assert name1 != name2
