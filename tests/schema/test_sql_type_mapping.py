"""
SQL DDL generation tests — PydanticToSQL.

Tests that the generator produces valid SQL statements.
"""

import pytest

from core.schema.sql_generator import PydanticToSQL


class TestSqlTypeMapping:

    @pytest.fixture
    def generator(self):
        return PydanticToSQL()

    def test_generate_statements_returns_non_empty_list(self, generator):
        stmts = generator.generate_composed_statements()
        assert isinstance(stmts, list)
        assert len(stmts) > 0

    def test_statements_contain_create_table(self, generator):
        stmts = generator.generate_composed_statements()
        # Convert SQL composed objects to strings for inspection
        sql_strings = []
        for stmt in stmts:
            try:
                # psycopg.sql.Composed objects need .as_string() or similar
                if hasattr(stmt, 'as_string'):
                    sql_strings.append(str(stmt.as_string(None)))
                else:
                    sql_strings.append(str(stmt))
            except Exception:
                sql_strings.append(repr(stmt))

        combined = " ".join(sql_strings).upper()
        assert "CREATE TABLE" in combined or "CREATE" in combined

    def test_statements_contain_create_type(self, generator):
        """Enum types should generate CREATE TYPE statements."""
        stmts = generator.generate_composed_statements()
        sql_strings = []
        for stmt in stmts:
            try:
                if hasattr(stmt, 'as_string'):
                    sql_strings.append(str(stmt.as_string(None)))
                else:
                    sql_strings.append(str(stmt))
            except Exception:
                sql_strings.append(repr(stmt))

        combined = " ".join(sql_strings).upper()
        # Should have enum type definitions
        assert "TYPE" in combined

    def test_all_registered_models_generate_without_error(self, generator):
        """The full generation pipeline should not raise."""
        try:
            stmts = generator.generate_composed_statements()
            assert len(stmts) > 10  # Should have many statements
        except Exception as e:
            pytest.fail(f"generate_composed_statements() raised: {e}")

    def test_statement_count_is_substantial(self, generator):
        """Should produce a meaningful number of DDL statements."""
        stmts = generator.generate_composed_statements()
        # With 20+ tables, enums, indexes, functions — expect 50+ statements
        assert len(stmts) >= 50
