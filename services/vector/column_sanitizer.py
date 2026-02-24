# ============================================================================
# COLUMN NAME SANITIZER
# ============================================================================
# STATUS: Service utility - Column name cleaning for PostGIS + TiPG compat
# PURPOSE: Prevent PostgresSyntaxError when TiPG queries tables with
#          reserved-word column names from source geodata files
# CREATED: 24 FEB 2026
# LAST_REVIEWED: 24 FEB 2026
# EXPORTS: sanitize_column_name, sanitize_columns, PG_RESERVED_WORDS
# ============================================================================
"""
Column Name Sanitizer for Vector ETL.

Provides canonical column name cleaning for geodata loaded into PostGIS.
Addresses three issues:

1. Source files (Shapefiles, GeoJSON, KML) commonly use column names
   that are PostgreSQL reserved words (type, name, date, order, etc.)

2. Our ETL uses psycopg sql.Identifier() which quotes these correctly,
   but TiPG generates its own SQL from information_schema and may not
   quote all column names — causing PostgresSyntaxError at query time.

3. OSM-sourced data uses colon-separated namespaces (addr:city, name:en)
   and other special characters that are invalid in PostgreSQL identifiers.

Solution: Replace all non-alphanumeric characters, prefix reserved words
with 'f_', truncate to 63 chars (PG NAMEDATALEN), and disambiguate
collisions when multiple source names map to the same sanitized name.

Exports:
    sanitize_column_name: Clean a single column name
    sanitize_columns: Clean a list of column names (preserves 'geometry',
                      detects collisions)
    PG_RESERVED_WORDS: frozenset of reserved words checked
"""

import logging
import re
from typing import List

logger = logging.getLogger(__name__)

# PostgreSQL NAMEDATALEN limit (63 bytes for identifiers)
PG_MAX_IDENTIFIER_LENGTH = 63


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
    6. Truncate to 63 characters (PostgreSQL NAMEDATALEN limit)
    7. Fallback to 'unnamed_column' for empty result

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
        >>> sanitize_column_name('addr:city')
        'addr_city'
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

    # Truncate to PostgreSQL NAMEDATALEN limit (63 chars)
    if len(cleaned) > PG_MAX_IDENTIFIER_LENGTH:
        cleaned = cleaned[:PG_MAX_IDENTIFIER_LENGTH].rstrip('_')

    return cleaned


def sanitize_columns(columns: List[str]) -> List[str]:
    """
    Sanitize a list of column names, preserving 'geometry'.

    Detects collisions where multiple source columns map to the same
    sanitized name (e.g., 'addr:city' and 'addr.city' both become
    'addr_city') and disambiguates by appending '_2', '_3', etc.

    Args:
        columns: List of column names from GeoDataFrame

    Returns:
        List of sanitized column names with collisions resolved
    """
    result = []
    seen = {}  # sanitized_name -> count of occurrences
    renames = []  # (original, sanitized) pairs that were disambiguated

    for col in columns:
        if col == 'geometry':
            result.append(col)
            continue

        sanitized = sanitize_column_name(col)

        if sanitized in seen:
            seen[sanitized] += 1
            disambiguated = f"{sanitized}_{seen[sanitized]}"
            # Ensure disambiguated name also respects length limit
            if len(disambiguated) > PG_MAX_IDENTIFIER_LENGTH:
                disambiguated = disambiguated[:PG_MAX_IDENTIFIER_LENGTH].rstrip('_')
            renames.append((col, disambiguated))
            result.append(disambiguated)
        else:
            seen[sanitized] = 1
            result.append(sanitized)

    if renames:
        logger.warning(
            "Column name collisions detected after sanitization. "
            "Disambiguated: %s",
            ", ".join(f"{orig!r} -> '{new}'" for orig, new in renames)
        )

    return result


# Module exports
__all__ = [
    'sanitize_column_name',
    'sanitize_columns',
    'PG_RESERVED_WORDS',
    'PG_MAX_IDENTIFIER_LENGTH',
]
