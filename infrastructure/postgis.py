"""
PostGIS Utility Functions.

Standalone helper functions for PostGIS database operations.
Used by jobs and validation logic to check database state.

Exports:
    check_table_exists: Check if a PostGIS table exists in a schema
"""

import psycopg
from typing import Optional
from config import get_config


def check_table_exists(schema: str, table_name: str) -> bool:
    """
    Check if a PostGIS table exists in the specified schema.

    Uses PostgreSQLRepository for connection management.
    Uses information_schema.tables to check for table existence.
    Does not require any special permissions beyond SELECT on information_schema.

    Args:
        schema: PostgreSQL schema name (e.g., 'geo', 'public', 'pgstac')
        table_name: Table name to check (case-sensitive)

    Returns:
        True if table exists, False otherwise

    Example:
        >>> from infrastructure.postgis import check_table_exists
        >>> if check_table_exists('geo', 'system_admin0'):
        ...     print("Table exists!")

    Raises:
        psycopg.Error: If database connection or query fails
    """
    from infrastructure.postgresql import PostgreSQLRepository

    repo = PostgreSQLRepository()

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                ) as exists
            """, (schema, table_name))

            result = cur.fetchone()
            # PostgreSQLRepository uses dict_row factory - access as dictionary, not tuple
            return result['exists'] if result else False
