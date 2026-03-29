"""Tests for preflight schema derivation helpers.

These tests validate _derive_expected_tables() and _derive_expected_enums()
against the Pydantic model registry. They run without a database connection.
"""

import pytest


class TestSchemaDerival:
    """Verify _derive_expected_tables returns correct table metadata."""

    def test_derive_expected_tables_returns_nonempty(self):
        from triggers.preflight_checks.database import _derive_expected_tables

        tables = _derive_expected_tables()
        assert len(tables) > 0

    def test_core_app_tables_present(self):
        from triggers.preflight_checks.database import _derive_expected_tables

        tables = _derive_expected_tables()
        table_names = {t["table"] for t in tables.values()}
        assert "jobs" in table_names
        assert "workflow_runs" in table_names
        assert "assets" in table_names

    def test_geo_tables_present(self):
        from triggers.preflight_checks.database import _derive_expected_tables

        tables = _derive_expected_tables()
        geo_tables = {t["table"] for key, t in tables.items() if t["schema"] == "geo"}
        assert "table_catalog" in geo_tables

    def test_etl_tracking_tables_present(self):
        from triggers.preflight_checks.database import _derive_expected_tables

        tables = _derive_expected_tables()
        table_names = {t["table"] for t in tables.values()}
        assert "vector_etl_tracking" in table_names
        assert "raster_render_configs" in table_names

    def test_each_table_has_columns(self):
        from triggers.preflight_checks.database import _derive_expected_tables

        tables = _derive_expected_tables()
        for key, meta in tables.items():
            assert len(meta["columns"]) > 0, f"Table {key} has no columns"

    def test_expected_enums_returns_nonempty(self):
        from triggers.preflight_checks.database import _derive_expected_enums

        enums = _derive_expected_enums()
        assert len(enums) > 0
        assert "job_status" in enums
        assert "workflow_run_status" in enums
        assert "approval_state" in enums
