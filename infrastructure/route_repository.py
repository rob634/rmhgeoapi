# ============================================================================
# CLAUDE CONTEXT - ROUTE REPOSITORY
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Infrastructure - Route table CRUD for geo.b2c_routes / geo.b2b_routes
# PURPOSE: Write/read/delete versioned route records for service layer routing
# LAST_REVIEWED: 02 MAR 2026
# EXPORTS: RouteRepository
# DEPENDENCIES: psycopg, infrastructure.postgresql
# ============================================================================
"""
Route Repository -- CRUD for geo.b2c_routes and geo.b2b_routes.

Provides upsert, delete, version promotion, and lookup operations for
the routing tables used by the service layer to resolve slugs to
PostGIS tables and STAC items.

Tables: geo.b2c_routes, geo.b2b_routes
Primary Key: (slug, version_id)
Unique Constraint: One is_latest=true per slug

Methods:
    UPSERT:
        upsert_route(route, table) - INSERT ON CONFLICT DO UPDATE

    READ:
        get_by_slug(slug, version, table) - Lookup by slug + version or latest

    UPDATE:
        clear_latest(slug, table) - Set is_latest=false for all versions of slug
        promote_next_latest(slug, table) - Promote highest ordinal to is_latest

    DELETE:
        delete_route(slug, version_id, table) - Remove single route entry

Exports:
    RouteRepository
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone

from psycopg import sql
from psycopg.rows import dict_row

from util_logger import LoggerFactory, ComponentType
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "RouteRepository")


class RouteRepository(PostgreSQLRepository):
    """
    Repository for geo.b2c_routes and geo.b2b_routes -- the routing tables
    that map slugs to PostGIS tables, STAC items, and blob paths.

    All methods accept a ``table`` parameter to select which route table
    to operate on. The table name is validated against VALID_TABLES to
    prevent SQL injection.
    """

    SCHEMA = "geo"
    VALID_TABLES = ("b2c_routes", "b2b_routes")

    # Columns written by upsert (order matches VALUES placeholder)
    UPSERT_COLUMNS = (
        "slug", "version_id", "data_type", "is_latest", "version_ordinal",
        "table_name", "stac_item_id", "stac_collection_id", "blob_path",
        "title", "description", "asset_id", "release_id",
        "cleared_by", "cleared_at", "created_at",
    )

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def _validate_table(self, table: str) -> str:
        """Validate table name against allowlist.

        Args:
            table: Table name to validate.

        Returns:
            The validated table name (unchanged).

        Raises:
            ValueError: If table name is not in VALID_TABLES.
        """
        if table not in self.VALID_TABLES:
            raise ValueError(
                f"Invalid route table '{table}'. "
                f"Must be one of: {', '.join(self.VALID_TABLES)}"
            )
        return table

    # =========================================================================
    # UPSERT
    # =========================================================================

    def upsert_route(self, route: Dict[str, Any], table: str = "b2c_routes") -> bool:
        """Insert or update a route entry.

        Uses INSERT ON CONFLICT (slug, version_id) DO UPDATE to upsert.
        All non-PK columns are updated on conflict.

        Args:
            route: Dict with column values. Must contain at least 'slug'
                   and 'version_id'. Missing optional columns default to None.
            table: Route table name ('b2c_routes' or 'b2b_routes').

        Returns:
            True on success.
        """
        self._validate_table(table)

        # Build values tuple in column order, defaulting missing keys to None
        route = dict(route)  # Don't mutate caller's dict
        if route.get("created_at") is None:
            route["created_at"] = datetime.now(timezone.utc)

        values = tuple(route.get(col) for col in self.UPSERT_COLUMNS)

        # Columns to update on conflict (everything except PK: slug, version_id)
        update_cols = [c for c in self.UPSERT_COLUMNS if c not in ("slug", "version_id")]
        update_clause = sql.SQL(", ").join(
            sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(c))
            for c in update_cols
        )

        placeholders = sql.SQL(", ").join(sql.SQL("%s") for _ in self.UPSERT_COLUMNS)
        col_names = sql.SQL(", ").join(sql.Identifier(c) for c in self.UPSERT_COLUMNS)

        query = sql.SQL("""
            INSERT INTO {schema}.{table} ({columns})
            VALUES ({placeholders})
            ON CONFLICT (slug, version_id) DO UPDATE SET
                {updates}
        """).format(
            schema=sql.Identifier(self.SCHEMA),
            table=sql.Identifier(table),
            columns=col_names,
            placeholders=placeholders,
            updates=update_clause,
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                conn.commit()
                logger.info(
                    f"Upserted route: {route.get('slug')} / "
                    f"{route.get('version_id')} -> {table}"
                )
                return True

    # =========================================================================
    # UPDATE
    # =========================================================================

    def clear_latest(self, slug: str, table: str = "b2c_routes") -> int:
        """Set is_latest=false for all versions of a slug.

        Called before promoting a new version to latest.

        Args:
            slug: The route slug.
            table: Route table name.

        Returns:
            Count of rows updated.
        """
        self._validate_table(table)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {schema}.{table}
                        SET is_latest = false
                        WHERE slug = %s AND is_latest = true
                    """).format(
                        schema=sql.Identifier(self.SCHEMA),
                        table=sql.Identifier(table),
                    ),
                    (slug,)
                )
                conn.commit()
                count = cur.rowcount
                if count:
                    logger.info(f"Cleared is_latest on {count} row(s) for slug '{slug}' in {table}")
                return count

    def promote_next_latest(self, slug: str, table: str = "b2c_routes") -> Optional[str]:
        """Promote the highest version_ordinal remaining for a slug to is_latest.

        Finds the row with the highest version_ordinal for the given slug
        and sets is_latest=true on it.

        Args:
            slug: The route slug.
            table: Route table name.

        Returns:
            version_id of the promoted version, or None if no rows remain.
        """
        self._validate_table(table)

        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Find highest ordinal remaining
                cur.execute(
                    sql.SQL("""
                        UPDATE {schema}.{table}
                        SET is_latest = true
                        WHERE (slug, version_ordinal) = (
                            SELECT slug, version_ordinal
                            FROM {schema}.{table}
                            WHERE slug = %s
                            ORDER BY version_ordinal DESC
                            LIMIT 1
                        )
                        RETURNING version_id
                    """).format(
                        schema=sql.Identifier(self.SCHEMA),
                        table=sql.Identifier(table),
                    ),
                    (slug,)
                )
                row = cur.fetchone()
                conn.commit()

                if row:
                    promoted = row["version_id"]
                    logger.info(
                        f"Promoted {promoted} to is_latest for slug '{slug}' in {table}"
                    )
                    return promoted

                logger.info(f"No remaining versions for slug '{slug}' in {table}")
                return None

    # =========================================================================
    # DELETE
    # =========================================================================

    def delete_route(self, slug: str, version_id: str, table: str = "b2c_routes") -> bool:
        """Delete a single route entry.

        Args:
            slug: The route slug.
            version_id: The version identifier (e.g. 'v1').
            table: Route table name.

        Returns:
            True if a row was deleted, False if no matching row.
        """
        self._validate_table(table)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        DELETE FROM {schema}.{table}
                        WHERE slug = %s AND version_id = %s
                    """).format(
                        schema=sql.Identifier(self.SCHEMA),
                        table=sql.Identifier(table),
                    ),
                    (slug, version_id)
                )
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.info(f"Deleted route: {slug} / {version_id} from {table}")
                return deleted

    # =========================================================================
    # READ
    # =========================================================================

    def get_by_slug(
        self,
        slug: str,
        version: str = "latest",
        table: str = "b2c_routes",
    ) -> Optional[Dict[str, Any]]:
        """Look up a route by slug and version.

        Args:
            slug: The route slug.
            version: Either 'latest' (default) to get the is_latest=true row,
                     or a specific version_id string (e.g. 'v1').
            table: Route table name.

        Returns:
            Dict of column:value for the matching row, or None if not found.
        """
        self._validate_table(table)

        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if version == "latest":
                    cur.execute(
                        sql.SQL("""
                            SELECT * FROM {schema}.{table}
                            WHERE slug = %s AND is_latest = true
                        """).format(
                            schema=sql.Identifier(self.SCHEMA),
                            table=sql.Identifier(table),
                        ),
                        (slug,)
                    )
                else:
                    cur.execute(
                        sql.SQL("""
                            SELECT * FROM {schema}.{table}
                            WHERE slug = %s AND version_id = %s
                        """).format(
                            schema=sql.Identifier(self.SCHEMA),
                            table=sql.Identifier(table),
                        ),
                        (slug, version)
                    )

                row = cur.fetchone()
                return dict(row) if row else None
