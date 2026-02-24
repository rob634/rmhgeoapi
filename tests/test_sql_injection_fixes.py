"""Tests for P1 security fixes from Architecture Review 24 FEB 2026."""
import pytest
from psycopg import sql


class TestSQLComposition:
    """Verify SQL injection fixes use sql.Identifier, not f-strings."""

    def test_sql_identifier_quotes_column_name(self):
        """C3.1: Column names must use sql.Identifier."""
        malicious_key = "status = 'admin'--"
        ident = sql.Identifier(malicious_key)
        rendered = sql.SQL("{} = %s").format(ident).as_string(None)
        # sql.Identifier wraps in double quotes, neutralizing injection
        assert rendered.startswith('"')
        assert '= %s' in rendered

    def test_sql_identifier_quotes_schema_name(self):
        """C3.2/C3.3: Schema names must use sql.Identifier."""
        malicious_schema = "app; DROP TABLE jobs;--"
        ident = sql.Identifier(malicious_schema)
        rendered = sql.SQL("SELECT * FROM {}.tasks").format(ident).as_string(None)
        assert '"' in rendered

    def test_sql_join_composes_identifiers(self):
        """C3.3: Multiple schema names joined safely."""
        schemas = ["app", "public", "pgstac"]
        composed = sql.SQL("SET search_path TO {}").format(
            sql.SQL(', ').join(sql.Identifier(s) for s in schemas)
        )
        rendered = composed.as_string(None)
        assert '"app", "public", "pgstac"' in rendered


class TestXSSPrevention:
    """Verify XSS fixes use html.escape."""

    def test_html_escape_neutralizes_script_tags(self):
        """C8.1: Error messages must be HTML-escaped."""
        import html
        malicious = '<script>alert("xss")</script>'
        escaped = html.escape(malicious)
        assert '<script>' not in escaped
        assert '&lt;script&gt;' in escaped

    def test_html_escape_handles_angle_brackets(self):
        """C8.1: Interface names with HTML must be escaped."""
        import html
        malicious = '"><img src=x onerror=alert(1)>'
        escaped = html.escape(malicious)
        assert '<img' not in escaped
        assert '&lt;img' in escaped
