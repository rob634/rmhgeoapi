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


from unittest.mock import patch, MagicMock


class TestVectorExists:
    """Test _vector_table_exists existence check."""

    @patch("triggers.platform.unpublish.PostgreSQLRepository")
    def test_returns_true_when_table_exists(self, mock_repo_cls):
        # Set up nested context manager mocks (connection -> cursor)
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"exists": True}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_repo_cls.return_value._get_connection.return_value.__enter__.return_value = mock_conn

        from triggers.platform.unpublish import _vector_table_exists
        exists, detail = _vector_table_exists("my_table", "geo")
        assert exists is True
        assert "my_table" in detail

    @patch("triggers.platform.unpublish.PostgreSQLRepository")
    def test_returns_false_when_table_missing(self, mock_repo_cls):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"exists": False}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_repo_cls.return_value._get_connection.return_value.__enter__.return_value = mock_conn

        from triggers.platform.unpublish import _vector_table_exists
        exists, detail = _vector_table_exists("ghost_table", "geo")
        assert exists is False
        assert "ghost_table" in detail
        assert "does not exist" in detail

    @patch("triggers.platform.unpublish.PostgreSQLRepository")
    def test_returns_true_on_db_error(self, mock_repo_cls):
        """Fail-open: DB errors should not produce false 404."""
        mock_repo_cls.return_value._get_connection.side_effect = Exception("connection refused")

        from triggers.platform.unpublish import _vector_table_exists
        exists, detail = _vector_table_exists("any_table", "geo")
        assert exists is True
        assert "Could not verify" in detail


class TestRasterExists:
    """Test _raster_stac_item_exists existence check."""

    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_true_when_item_exists(self, mock_repo_cls):
        mock_repo_cls.return_value.get_item.return_value = {"id": "item-1"}

        from triggers.platform.unpublish import _raster_stac_item_exists
        exists, detail = _raster_stac_item_exists("item-1", "collection-1")
        assert exists is True

    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_false_when_item_missing(self, mock_repo_cls):
        mock_repo_cls.return_value.get_item.return_value = None

        from triggers.platform.unpublish import _raster_stac_item_exists
        exists, detail = _raster_stac_item_exists("ghost-item", "collection-1")
        assert exists is False
        assert "ghost-item" in detail
        assert "not found" in detail


class TestZarrExists:
    """Test _zarr_item_exists -- checks pgstac THEN Release fallback."""

    @patch("infrastructure.ReleaseRepository")
    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_true_when_in_pgstac(self, mock_pgstac_cls, mock_release_cls):
        mock_pgstac_cls.return_value.get_item.return_value = {"id": "zarr-1"}

        from triggers.platform.unpublish import _zarr_item_exists
        exists, detail = _zarr_item_exists("zarr-1", "coll-1")
        assert exists is True

    @patch("infrastructure.ReleaseRepository")
    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_true_when_in_release_only(self, mock_pgstac_cls, mock_rel_cls):
        mock_pgstac_cls.return_value.get_item.return_value = None
        mock_release = MagicMock()
        mock_release.stac_item_json = {"id": "zarr-1"}
        mock_rel_cls.return_value.get_by_stac_item_id.return_value = mock_release

        from triggers.platform.unpublish import _zarr_item_exists
        exists, detail = _zarr_item_exists("zarr-1", "coll-1")
        assert exists is True
        assert "Release" in detail

    @patch("infrastructure.ReleaseRepository")
    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_false_when_nowhere(self, mock_pgstac_cls, mock_rel_cls):
        mock_pgstac_cls.return_value.get_item.return_value = None
        mock_rel_cls.return_value.get_by_stac_item_id.return_value = None

        from triggers.platform.unpublish import _zarr_item_exists
        exists, detail = _zarr_item_exists("ghost-zarr", "coll-1")
        assert exists is False
        assert "ghost-zarr" in detail
        assert "not found" in detail

    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_true_on_both_lookups_error(self, mock_pgstac_cls):
        """Fail-open: if both pgstac and Release error out, proceed."""
        mock_pgstac_cls.return_value.get_item.side_effect = Exception("pgstac down")

        with patch("infrastructure.ReleaseRepository") as mock_rel_cls:
            mock_rel_cls.return_value.get_by_stac_item_id.side_effect = Exception("release down")

            from triggers.platform.unpublish import _zarr_item_exists
            exists, detail = _zarr_item_exists("any-zarr", "coll-1")
            assert exists is True
            assert "Could not verify" in detail


class TestMultiSourceExists:
    """Test _release_tables_exist."""

    def test_returns_true_when_tables_found(self):
        mock_rt = MagicMock()
        mock_rt.table_name = "table_a"
        with patch("infrastructure.release_table_repository.ReleaseTableRepository") as mock_cls:
            mock_cls.return_value.get_tables.return_value = [mock_rt]

            from triggers.platform.unpublish import _release_tables_exist
            exists, detail = _release_tables_exist("rel-123")
            assert exists is True
            assert "1 table" in detail

    def test_returns_false_when_no_tables(self):
        with patch("infrastructure.release_table_repository.ReleaseTableRepository") as mock_cls:
            mock_cls.return_value.get_tables.return_value = []

            from triggers.platform.unpublish import _release_tables_exist
            exists, detail = _release_tables_exist("rel-ghost")
            assert exists is False
            assert "rel-ghost" in detail
            assert "no tables" in detail.lower()
