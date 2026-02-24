# ============================================================================
# COLUMN NAME SANITIZER
# ============================================================================
# STATUS: Service utility - Column name cleaning for PostGIS + TiPG compat
# PURPOSE: Prevent PostgresSyntaxError when TiPG queries tables with
#          reserved-word column names from source geodata files
# CREATED: 24 FEB 2026
# EXPORTS: sanitize_column_name, PG_RESERVED_WORDS
# ============================================================================
"""
Column Name Sanitizer for Vector ETL.

Provides canonical column name cleaning for geodata loaded into PostGIS.
Addresses two issues:

1. Source files (Shapefiles, GeoJSON, KML) commonly use column names
   that are PostgreSQL reserved words (type, name, date, order, etc.)

2. Our ETL uses psycopg sql.Identifier() which quotes these correctly,
   but TiPG generates its own SQL from information_schema and may not
   quote all column names — causing PostgresSyntaxError at query time.

Solution: Prefix reserved words with 'f_' at ETL time so neither our
code nor TiPG needs to worry about quoting.

Exports:
    sanitize_column_name: Clean a single column name
    sanitize_columns: Clean a list of column names (preserves 'geometry')
    PG_RESERVED_WORDS: frozenset of reserved words checked
"""

import re
from typing import List


# PostgreSQL reserved words commonly found in geodata column names.
# Not exhaustive — focused on words that appear in real Shapefiles/GeoJSON.
# Full list: https://www.postgresql.org/docs/current/sql-keywords-appendix.html
PG_RESERVED_WORDS = frozenset({
    # SQL keywords
    'all', 'and', 'any', 'as', 'asc', 'between', 'by', 'case', 'cast',
    'check', 'column', 'constraint', 'create', 'cross', 'default', 'delete',
    'desc', 'do', 'else', 'end', 'except', 'exists', 'for', 'foreign',
    'from', 'full', 'grant', 'group', 'having', 'in', 'index', 'inner',
    'insert', 'intersect', 'into', 'is', 'left', 'like', 'limit', 'natural',
    'not', 'null', 'offset', 'on', 'or', 'order', 'outer', 'primary',
    'references', 'revoke', 'right', 'select', 'set', 'table', 'then',
    'to', 'union', 'update', 'using', 'when', 'where', 'with',
    # PostgreSQL-specific reserved words common in geodata
    'access', 'action', 'add', 'alter', 'begin', 'comment', 'commit',
    'date', 'drop', 'key', 'level', 'name', 'position', 'range',
    'result', 'role', 'row', 'rows', 'rule', 'some', 'time',
    'type', 'user', 'value', 'zone',
    # Common abbreviations that clash
    'abort', 'analyse', 'analyze',
})


def sanitize_column_name(name: str) -> str:
    """
    Sanitize a column name for safe use in PostGIS AND TiPG.

    Rules applied in order:
    1. Lowercase
    2. Replace non-alphanumeric characters with underscore
    3. Collapse consecutive underscores, strip leading/trailing
    4. Prefix digit-leading names with 'col_'
    5. Prefix PostgreSQL reserved words with 'f_' (field)
    6. Fallback to 'unnamed_column' for empty result

    Args:
        name: Raw column name from source file

    Returns:
        Sanitized column name safe for PostgreSQL and TiPG

    Examples:
        >>> sanitize_column_name('Type')
        'f_type'
        >>> sanitize_column_name('ORDER')
        'f_order'
        >>> sanitize_column_name('Feature Name')
        'feature_name'
        >>> sanitize_column_name('2024_population')
        'col_2024_population'
        >>> sanitize_column_name('résultat')
        'r_sultat'
    """
    cleaned = name.lower()
    cleaned = re.sub(r'[^a-z0-9_]', '_', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')

    if not cleaned:
        return 'unnamed_column'

    if cleaned[0].isdigit():
        cleaned = 'col_' + cleaned

    if cleaned in PG_RESERVED_WORDS:
        cleaned = 'f_' + cleaned

    return cleaned


def sanitize_columns(columns: List[str]) -> List[str]:
    """
    Sanitize a list of column names, preserving 'geometry'.

    Args:
        columns: List of column names from GeoDataFrame

    Returns:
        List of sanitized column names
    """
    return [
        col if col == 'geometry' else sanitize_column_name(col)
        for col in columns
    ]


# Module exports
__all__ = [
    'sanitize_column_name',
    'sanitize_columns',
    'PG_RESERVED_WORDS',
]
