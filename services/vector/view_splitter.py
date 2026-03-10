# ============================================================================
# VECTOR VIEW SPLITTER
# ============================================================================
# STATUS: Service utility - Per-value PostgreSQL views for PostGIS tables
# PURPOSE: Split a table into filtered views based on a categorical column
# CREATED: 09 MAR 2026
# EXPORTS: validate_split_column, discover_split_values, create_split_views,
#          register_split_views, cleanup_split_view_metadata
# DEPENDENCIES: psycopg, services.vector.column_sanitizer
# ============================================================================
"""
Vector View Splitter.

After a vector table is uploaded to PostGIS, this module can split it into
multiple PostgreSQL VIEWs — one per distinct value in a categorical column.
Each view auto-registers in PostGIS geometry_columns and is auto-discovered
by TiPG as a separate OGC Feature collection.

Example:
    Table: geo.admin_boundaries_ord1 (columns: id, geom, admin_level, name)
    split_column: "admin_level"
    Distinct values: [0, 1, 2]

    Creates:
        VIEW geo.admin_boundaries_ord1_admin_level_0
             AS SELECT * FROM geo.admin_boundaries_ord1 WHERE admin_level = 0
        VIEW geo.admin_boundaries_ord1_admin_level_1
             AS SELECT * FROM geo.admin_boundaries_ord1 WHERE admin_level = 1
        VIEW geo.admin_boundaries_ord1_admin_level_2
             AS SELECT * FROM geo.admin_boundaries_ord1 WHERE admin_level = 2

Design:
    - Views use the base table's GIST spatial index (zero overhead)
    - CREATE OR REPLACE VIEW for idempotency
    - All views created in one transaction (atomic)
    - Catalog entries use INSERT ... ON CONFLICT DO UPDATE (idempotent)
    - DROP TABLE CASCADE on base table auto-drops all views

Exports:
    validate_split_column: Check column exists and has categorical type
    discover_split_values: Query DISTINCT values, enforce cardinality limit
    create_split_views: CREATE VIEW for each value
    register_split_views: Create geo.table_catalog entries for each view
    cleanup_split_view_metadata: Delete stale catalog entries before re-creation
"""

import json
import re
from typing import Any, Dict, List, Optional

from psycopg import sql

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "view_splitter")

# ============================================================================
# CONSTANTS
# ============================================================================

# Hard cap on distinct values. Rejects if exceeded.
MAX_SPLIT_CARDINALITY = 20

# PostgreSQL NAMEDATALEN limit (63 bytes for identifiers)
PG_MAX_IDENTIFIER_LENGTH = 63

# PostgreSQL data types that are safe to split on (categorical).
ALLOWED_SPLIT_TYPES = frozenset({
    # Text types
    'text', 'character varying', 'varchar', 'character', 'char', 'bpchar',
    # Integer types
    'integer', 'int4', 'smallint', 'int2', 'bigint', 'int8',
    # Boolean
    'boolean', 'bool',
})

# Types explicitly rejected (informative error message).
REJECTED_SPLIT_TYPES_DISPLAY = (
    "float/double, numeric/decimal, geometry, geography, "
    "jsonb, json, bytea, uuid, timestamp, date, time"
)


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _sanitize_view_name_segment(value: Any) -> str:
    """
    Convert a split column value to a safe PostgreSQL identifier segment.

    Rules:
        1. str(value).lower()
        2. Replace non-alphanumeric with underscore
        3. Collapse consecutive underscores, strip leading/trailing
        4. Fallback to 'val' if empty
    """
    text = str(value).lower()
    text = re.sub(r'[^a-z0-9_]', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text if text else 'val'


def _compute_view_name(table_name: str, split_column: str, value: Any) -> str:
    """
    Compute the view name: {table}_{column}_{value}, truncated to 63 chars.

    Truncation strategy (preserves readability):
        1. If full name fits in 63 chars, use it
        2. Otherwise, shorten table_name prefix (keep column+value)
        3. If suffix alone > 55 chars, shorten value too
        4. Raise ValueError if impossible (pathological)
    """
    sanitized_value = _sanitize_view_name_segment(value)
    suffix = f"_{split_column}_{sanitized_value}"
    ideal = f"{table_name}{suffix}"

    if len(ideal) <= PG_MAX_IDENTIFIER_LENGTH:
        return ideal

    # Truncate table_name, preserve suffix
    max_table_len = PG_MAX_IDENTIFIER_LENGTH - len(suffix)
    if max_table_len >= 8:
        truncated = table_name[:max_table_len].rstrip('_')
        return f"{truncated}{suffix}"

    # Suffix too long — truncate value segment too
    max_val_len = PG_MAX_IDENTIFIER_LENGTH - len(table_name) - len(split_column) - 2
    if max_val_len < 3:
        raise ValueError(
            f"Cannot generate view name within 63-char limit for "
            f"table='{table_name}', column='{split_column}', value='{value}'"
        )
    sanitized_value = sanitized_value[:max_val_len]
    return f"{table_name}_{split_column}_{sanitized_value}"


# ============================================================================
# PUBLIC API
# ============================================================================

def validate_split_column(
    conn,
    table_name: str,
    schema: str,
    split_column: str
) -> Dict[str, Any]:
    """
    Validate that split_column exists in the table and has a categorical type.

    Args:
        conn: Open psycopg connection (dict_row cursor factory)
        table_name: Base table name (already created in PostGIS)
        schema: Schema name (e.g., 'geo')
        split_column: Column name to validate (post-sanitization)

    Returns:
        {'column_name': str, 'data_type': str}

    Raises:
        ValueError: Column not found, or type not categorical
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table_name))
        columns = {row['column_name']: row for row in cur.fetchall()}

    # Reserved columns the user should never split on
    reserved = {'id', 'geom', 'geometry', 'etl_batch_id'}

    if split_column not in columns:
        available = sorted(c for c in columns if c not in reserved)
        raise ValueError(
            f"Split column '{split_column}' not found in {schema}.{table_name}. "
            f"Available columns (post-sanitization): {available}. "
            f"Note: column names are sanitized during upload — "
            f"'Type' becomes 'f_type', 'Feature Name' becomes 'feature_name'."
        )

    if split_column in reserved:
        raise ValueError(
            f"Cannot split on reserved column '{split_column}'. "
            f"Choose a data column, not a system column."
        )

    col_info = columns[split_column]
    pg_type = col_info['data_type']
    udt_name = col_info['udt_name']

    if pg_type not in ALLOWED_SPLIT_TYPES and udt_name not in ALLOWED_SPLIT_TYPES:
        raise ValueError(
            f"Split column '{split_column}' has type '{pg_type}' which is not categorical. "
            f"Allowed types: text, varchar, integer, smallint, bigint, boolean. "
            f"Not allowed: {REJECTED_SPLIT_TYPES_DISPLAY}."
        )

    logger.info(f"Split column '{split_column}' validated: type={pg_type}")
    return {'column_name': split_column, 'data_type': pg_type}


def discover_split_values(
    conn,
    table_name: str,
    schema: str,
    split_column: str,
    max_cardinality: int = MAX_SPLIT_CARDINALITY
) -> List[Any]:
    """
    Query DISTINCT non-NULL values from the split column.

    Two-step: COUNT(DISTINCT) first (cheap), then SELECT DISTINCT (bounded).

    Returns:
        Sorted list of distinct non-NULL values

    Raises:
        ValueError: All NULL, or cardinality exceeds limit
    """
    with conn.cursor() as cur:
        # Cheap cardinality check
        cur.execute(
            sql.SQL(
                "SELECT COUNT(DISTINCT {col}) AS cnt "
                "FROM {schema}.{table} WHERE {col} IS NOT NULL"
            ).format(
                col=sql.Identifier(split_column),
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
            )
        )
        count = cur.fetchone()['cnt']

        if count == 0:
            raise ValueError(
                f"Split column '{split_column}' contains only NULL values "
                f"in {schema}.{table_name}. Cannot create views."
            )

        if count > max_cardinality:
            raise ValueError(
                f"Split column '{split_column}' has {count} distinct values, "
                f"exceeding the maximum of {max_cardinality}. "
                f"Use a column with fewer categories."
            )

        # Fetch actual values (bounded by max_cardinality)
        cur.execute(
            sql.SQL(
                "SELECT DISTINCT {col} FROM {schema}.{table} "
                "WHERE {col} IS NOT NULL ORDER BY {col}"
            ).format(
                col=sql.Identifier(split_column),
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
            )
        )
        values = [row[split_column] for row in cur.fetchall()]

    logger.info(f"Discovered {len(values)} distinct values for '{split_column}': {values}")
    return values


def create_split_views(
    conn,
    table_name: str,
    schema: str,
    split_column: str,
    values: List[Any],
) -> List[Dict[str, Any]]:
    """
    Create one PostgreSQL VIEW per distinct value.

    Uses CREATE OR REPLACE VIEW for idempotency.
    All views created in caller's transaction (atomic — commit externally).

    Returns:
        List of dicts: [{'view_name': str, 'value': Any, 'qualified_name': str}]
    """
    views_created = []

    with conn.cursor() as cur:
        for value in values:
            view_name = _compute_view_name(table_name, split_column, value)

            logger.info(f"Creating view {schema}.{view_name} WHERE {split_column} = {value!r}")

            cur.execute(
                sql.SQL(
                    "CREATE OR REPLACE VIEW {schema}.{view} AS "
                    "SELECT * FROM {schema}.{table} "
                    "WHERE {col} = {val}"
                ).format(
                    schema=sql.Identifier(schema),
                    view=sql.Identifier(view_name),
                    table=sql.Identifier(table_name),
                    col=sql.Identifier(split_column),
                    val=sql.Literal(value),
                )
            )

            views_created.append({
                'view_name': view_name,
                'value': value,
                'qualified_name': f"{schema}.{view_name}",
            })

    logger.info(f"Created {len(views_created)} split views for {schema}.{table_name}")
    return views_created


def register_split_views(
    conn,
    views: List[Dict[str, Any]],
    base_table_name: str,
    schema: str,
    split_column: str,
    base_title: Optional[str] = None,
    geometry_type: Optional[str] = None,
    srid: int = 4326,
) -> int:
    """
    Register each split view in geo.table_catalog.

    Uses INSERT ... ON CONFLICT DO UPDATE for idempotency.

    Returns:
        Number of catalog entries created
    """
    registered = 0

    with conn.cursor() as cur:
        for view_info in views:
            view_name = view_info['view_name']
            value = view_info['value']

            # Feature count
            cur.execute(
                sql.SQL("SELECT COUNT(*) AS cnt FROM {schema}.{view}").format(
                    schema=sql.Identifier(schema),
                    view=sql.Identifier(view_name),
                )
            )
            feature_count = cur.fetchone()['cnt']

            # Bounding box
            cur.execute(
                sql.SQL(
                    "SELECT "
                    "ST_XMin(ext) AS minx, ST_YMin(ext) AS miny, "
                    "ST_XMax(ext) AS maxx, ST_YMax(ext) AS maxy "
                    "FROM (SELECT ST_Extent({geom}) AS ext "
                    "FROM {schema}.{view}) sub"
                ).format(
                    geom=sql.Identifier('geom'),
                    schema=sql.Identifier(schema),
                    view=sql.Identifier(view_name),
                )
            )
            bbox = cur.fetchone()

            # Derive title
            value_label = str(value)
            view_title = (
                f"{base_title} — {split_column} {value_label}"
                if base_title
                else f"{base_table_name} — {split_column} {value_label}"
            )

            custom_props = json.dumps({
                'split_view': True,
                'base_table': base_table_name,
                'split_column': split_column,
                'split_value': value,
            })

            cur.execute("""
                INSERT INTO geo.table_catalog (
                    table_name, schema_name, title,
                    geometry_type, srid, feature_count,
                    bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
                    table_type, custom_properties,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    'split_view', %s,
                    NOW(), NOW()
                )
                ON CONFLICT (table_name) DO UPDATE SET
                    title = EXCLUDED.title,
                    geometry_type = EXCLUDED.geometry_type,
                    feature_count = EXCLUDED.feature_count,
                    bbox_minx = EXCLUDED.bbox_minx,
                    bbox_miny = EXCLUDED.bbox_miny,
                    bbox_maxx = EXCLUDED.bbox_maxx,
                    bbox_maxy = EXCLUDED.bbox_maxy,
                    table_type = EXCLUDED.table_type,
                    custom_properties = EXCLUDED.custom_properties,
                    updated_at = NOW()
            """, (
                view_name, schema, view_title,
                geometry_type, srid, feature_count,
                bbox['minx'], bbox['miny'], bbox['maxx'], bbox['maxy'],
                custom_props,
            ))

            registered += 1
            logger.info(
                f"Registered catalog: {view_name} "
                f"({feature_count} features, "
                f"bbox=[{bbox['minx']:.4f},{bbox['miny']:.4f},"
                f"{bbox['maxx']:.4f},{bbox['maxy']:.4f}])"
            )

    logger.info(f"Registered {registered} split view catalog entries for {schema}.{base_table_name}")
    return registered


def cleanup_split_view_metadata(conn, base_table_name: str) -> int:
    """
    Delete geo.table_catalog entries for split views of a base table.

    Called before re-creating views (overwrite) or when base table is dropped.
    The actual PostgreSQL views are dropped by DROP TABLE CASCADE.
    This function only cleans up the metadata.

    Returns:
        Number of catalog entries deleted
    """
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM geo.table_catalog
            WHERE table_type = 'split_view'
            AND custom_properties->>'base_table' = %s
            RETURNING table_name
        """, (base_table_name,))
        deleted = cur.fetchall()

    count = len(deleted)
    if count > 0:
        names = [r['table_name'] for r in deleted]
        logger.info(f"Cleaned up {count} stale split view catalog entries: {names}")
    return count


__all__ = [
    'validate_split_column',
    'discover_split_values',
    'create_split_views',
    'register_split_views',
    'cleanup_split_view_metadata',
    'MAX_SPLIT_CARDINALITY',
    'ALLOWED_SPLIT_TYPES',
]
