# tests/unit/test_unpublish_existence.py
"""Tests for unpublish existence validation."""

import json
import pytest


class TestNotFoundResponse:
    """Test the not_found_error response builder."""

    def test_not_found_returns_404(self):
        from services.platform_response import not_found_error
        resp = not_found_error("Table 'geo.my_table' does not exist")
        assert resp.status_code == 404

    def test_not_found_includes_error_message(self):
        from services.platform_response import not_found_error
        resp = not_found_error("Table 'geo.my_table' does not exist")
        body = json.loads(resp.get_body())
        assert body["error"] == "Table 'geo.my_table' does not exist"
        assert body["error_type"] == "NotFoundError"

    def test_not_found_includes_extra_fields(self):
        from services.platform_response import not_found_error
        resp = not_found_error(
            "STAC item 'x' not found",
            stac_item_id="x",
            collection_id="y"
        )
        body = json.loads(resp.get_body())
        assert body["stac_item_id"] == "x"
        assert body["collection_id"] == "y"
