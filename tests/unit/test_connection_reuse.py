# ============================================================================
# TESTS: CONNECTION REUSE IN VECTOR ETL
# ============================================================================
# PURPOSE: Verify postgis_handler methods use provided connections
#          instead of opening new ones (11 MAR 2026)
# ============================================================================
"""
Tests for connection reuse in VectorToPostGISHandler.

Verifies that when a connection is passed in, methods use it
instead of opening a new one. Also verifies backward compatibility:
when conn=None (default), methods open their own connection.
"""
import pytest
from unittest.mock import MagicMock, patch


def _make_mock_conn():
    """Create a mock connection with cursor context manager."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 0
    mock_cursor.fetchone.return_value = {'count': 5, 'exists': False}
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def _make_handler():
    """Create a VectorToPostGISHandler without __init__ (no DB connection)."""
    from services.vector.postgis_handler import VectorToPostGISHandler
    handler = VectorToPostGISHandler.__new__(VectorToPostGISHandler)
    handler._pg_repo = MagicMock()
    return handler


class TestInsertChunkIdempotentConnReuse:
    """insert_chunk_idempotent should use passed connection, not open new one."""

    def test_uses_provided_connection(self):
        """When conn is passed, _get_connection should NOT be called."""
        handler = _make_handler()
        mock_conn, _ = _make_mock_conn()

        import geopandas as gpd
        from shapely.geometry import Point
        gdf = gpd.GeoDataFrame({'geometry': [Point(0, 0)]}, crs=None)

        handler.insert_chunk_idempotent(
            chunk=gdf,
            table_name="test",
            schema="geo",
            batch_id="test-chunk-0",
            conn=mock_conn
        )

        handler._pg_repo._get_connection.assert_not_called()

    def test_opens_own_connection_when_none(self):
        """When conn=None (default), opens own connection (backward compat)."""
        handler = _make_handler()
        mock_conn, _ = _make_mock_conn()

        handler._pg_repo._get_connection.return_value.__enter__ = lambda s: mock_conn
        handler._pg_repo._get_connection.return_value.__exit__ = MagicMock(return_value=False)

        import geopandas as gpd
        from shapely.geometry import Point
        gdf = gpd.GeoDataFrame({'geometry': [Point(0, 0)]}, crs=None)

        handler.insert_chunk_idempotent(
            chunk=gdf,
            table_name="test",
            schema="geo",
            batch_id="test-chunk-0",
        )

        handler._pg_repo._get_connection.assert_called_once()


class TestAnalyzeTableConnReuse:
    def test_uses_provided_connection(self):
        handler = _make_handler()
        mock_conn, _ = _make_mock_conn()

        handler.analyze_table("test_table", "geo", conn=mock_conn)

        handler._pg_repo._get_connection.assert_not_called()


class TestCreateDeferredIndexesConnReuse:
    def test_uses_provided_connection(self):
        handler = _make_handler()
        mock_conn, _ = _make_mock_conn()

        import geopandas as gpd
        from shapely.geometry import Point
        gdf = gpd.GeoDataFrame({'col1': [1], 'geometry': [Point(0, 0)]}, crs=None)

        handler.create_deferred_indexes("test", "geo", gdf, conn=mock_conn)

        handler._pg_repo._get_connection.assert_not_called()


class TestCreateTableWithBatchTrackingConnReuse:
    def test_uses_provided_connection(self):
        handler = _make_handler()
        mock_conn, mock_cursor = _make_mock_conn()
        # table exists check returns False
        mock_cursor.fetchone.return_value = {'exists': False}

        import geopandas as gpd
        from shapely.geometry import Point
        gdf = gpd.GeoDataFrame({'col1': [1], 'geometry': [Point(0, 0)]}, crs=None)

        handler.create_table_with_batch_tracking(
            table_name="test", schema="geo", gdf=gdf, conn=mock_conn
        )

        handler._pg_repo._get_connection.assert_not_called()
