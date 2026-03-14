# ============================================================================
# CLAUDE CONTEXT - DATABASE_UTILITIES
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Shared database utilities
# PURPOSE: psycopg3 type adapters, JSONB parsing, connection string redaction
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: register_type_adapters, parse_jsonb_column, redact_connection_string
# DEPENDENCIES: psycopg, json, logging (no infrastructure imports — leaf node)
# ============================================================================
"""
Database utilities shared across infrastructure components.

Contains psycopg3 type adapters (dict/list -> JSONB, Enum -> .value) and
JSONB column parsing. These are module-level functions registered on each
connection -- not class methods.

Import graph: This module is a leaf node.
    db_utils.py <- db_connections.py, postgresql.py, connection_pool.py
"""

import json
import logging
from typing import Any
from enum import Enum

from psycopg.types.json import JsonbBinaryDumper
from psycopg.adapt import Dumper

from exceptions import DatabaseError

logger = logging.getLogger(__name__)


class _EnumDumper(Dumper):
    """Adapt any Enum subclass -> its .value for psycopg3."""

    def dump(self, obj):
        return str(obj.value).encode('utf-8')


def register_type_adapters(conn) -> None:
    """
    Register psycopg3 type adapters on a connection.

    Called for both single-use (Function App) and pooled (Docker) connections.
    After registration, dict/list auto-serialize to JSONB and Enum subclasses
    auto-serialize to their .value -- no manual json.dumps() or .value needed.
    """
    conn.adapters.register_dumper(dict, JsonbBinaryDumper)
    conn.adapters.register_dumper(list, JsonbBinaryDumper)
    conn.adapters.register_dumper(Enum, _EnumDumper)


def parse_jsonb_column(value: Any, column_name: str, record_id: str, default: Any = None) -> Any:
    """
    Parse a JSONB column value with explicit error handling.

    Replaces silent fallbacks that hide data corruption. Logs errors
    and raises DatabaseError on malformed JSON.

    Args:
        value: The raw value from PostgreSQL (could be dict, str, or None)
        column_name: Name of the column for error context
        record_id: Job/task ID for error context
        default: Default value if column is NULL (not for parse errors!)

    Returns:
        Parsed dict/value or default if NULL

    Raises:
        DatabaseError: If JSON parsing fails (data corruption)
    """
    if value is None:
        return default

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(
                f"Corrupted JSON in {column_name} for {record_id[:16]}...: {e}",
                extra={
                    'record_id': record_id,
                    'column': column_name,
                    'error_type': 'JSONDecodeError',
                    'preview': value[:200] if len(value) > 200 else value
                }
            )
            raise DatabaseError(f"Corrupted {column_name} JSON for {record_id}: {e}")

    logger.error(
        f"Unexpected type for {column_name}: {type(value).__name__}",
        extra={'record_id': record_id, 'column': column_name, 'value_type': type(value).__name__}
    )
    raise DatabaseError(f"Unexpected type for {column_name}: {type(value).__name__}")


def redact_connection_string(conn_str: str) -> str:
    """
    Redact password/token from a PostgreSQL connection string for safe logging.

    Handles both URI format (postgresql://user:pass@host/db) and
    key=value format (host=x password=token sslmode=require).
    """
    import re
    # key=value format: password=<token> sslmode=...
    redacted = re.sub(r'password=\S+', 'password=***REDACTED***', conn_str)
    # URI format: postgresql://user:password@host
    redacted = re.sub(r'://([^:]+):([^@]+)@', r'://\1:***REDACTED***@', redacted)
    return redacted


__all__ = ['register_type_adapters', 'parse_jsonb_column', 'redact_connection_string']
