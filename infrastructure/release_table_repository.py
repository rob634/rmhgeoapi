# ============================================================================
# CLAUDE CONTEXT - RELEASE TABLE REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Repository - CRUD for app.release_tables junction table
# PURPOSE: Single source of truth for Release → PostGIS table relationships
# LAST_REVIEWED: 26 FEB 2026
# EXPORTS: ReleaseTableRepository
# DEPENDENCIES: psycopg, core.models.release_table
# ============================================================================
"""
Release Table Repository.

CRUD operations for app.release_tables — the junction table linking
releases to their PostGIS output tables.

This is the SINGLE SOURCE OF TRUTH for which tables a release owns.

Table: app.release_tables
Primary Key: (release_id, table_name)
Foreign Key: release_id → app.asset_releases(release_id)

Methods:
    CREATE:
        create(release_id, table_name, ...) - Insert single entry
        create_batch(entries) - Insert multiple entries in one transaction

    READ:
        get_tables(release_id) - All tables for a release
        get_primary_table(release_id) - Primary table (or first)
        get_by_table_name(table_name) - Find which release owns a table
        get_table_names(release_id) - Just the table name strings

    UPDATE:
        update_feature_count(release_id, table_name, count) - Update count

    DELETE:
        delete_for_release(release_id) - Remove all entries for a release

Exports:
    ReleaseTableRepository
"""

from typing import List, Optional
from datetime import datetime, timezone

from psycopg import sql
from psycopg.rows import dict_row

from util_logger import LoggerFactory, ComponentType
from core.models.release_table import ReleaseTable
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "ReleaseTableRepository")


class ReleaseTableRepository(PostgreSQLRepository):
    """
    Repository for app.release_tables — the junction table linking
    releases to their PostGIS output tables.

    This is the SINGLE SOURCE OF TRUTH for which tables a release owns.
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.schema = "app"
        self.table = "release_tables"

    # =========================================================================
    # CREATE
    # =========================================================================

    def create(
        self,
        release_id: str,
        table_name: str,
        geometry_type: str,
        table_role: str = "primary",
        table_suffix: Optional[str] = None,
        feature_count: int = 0
    ) -> ReleaseTable:
        """Insert a single release_tables row."""
        now = datetime.now(timezone.utc)

        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            release_id, table_name, geometry_type,
                            feature_count, table_role, table_suffix,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id, table_name, geometry_type,
                     feature_count, table_role, table_suffix, now)
                )
                row = cur.fetchone()
                conn.commit()
                logger.info(f"Created release_table: {release_id[:12]}... -> {table_name}")
                return self._row_to_model(row)

    def create_batch(self, entries: List[ReleaseTable]) -> List[ReleaseTable]:
        """Insert multiple release_tables rows in one transaction."""
        if not entries:
            return []

        now = datetime.now(timezone.utc)
        results = []

        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                for entry in entries:
                    cur.execute(
                        sql.SQL("""
                            INSERT INTO {}.{} (
                                release_id, table_name, geometry_type,
                                feature_count, table_role, table_suffix,
                                created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING *
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        ),
                        (entry.release_id, entry.table_name, entry.geometry_type,
                         entry.feature_count, entry.table_role, entry.table_suffix, now)
                    )
                    row = cur.fetchone()
                    results.append(self._row_to_model(row))

                conn.commit()
                logger.info(f"Created {len(results)} release_table entries for {entries[0].release_id[:12]}...")
                return results

    # =========================================================================
    # READ
    # =========================================================================

    def get_tables(self, release_id: str) -> List[ReleaseTable]:
        """Get ALL tables owned by a release."""
        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE release_id = %s
                        ORDER BY table_role, table_name
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id,)
                )
                rows = cur.fetchall()
                return [self._row_to_model(r) for r in rows]

    def get_primary_table(self, release_id: str) -> Optional[ReleaseTable]:
        """Get the primary table for a release (or first table if geometry_split)."""
        tables = self.get_tables(release_id)
        if not tables:
            return None
        # Prefer 'primary' role, fall back to first entry
        for t in tables:
            if t.table_role == 'primary':
                return t
        return tables[0]

    def get_by_table_name(self, table_name: str) -> Optional[ReleaseTable]:
        """Find which release owns a given table."""
        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE table_name = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (table_name,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_table_names(self, release_id: str) -> List[str]:
        """Get just the table names for a release (convenience method)."""
        tables = self.get_tables(release_id)
        return [t.table_name for t in tables]

    # =========================================================================
    # UPDATE
    # =========================================================================

    def update_feature_count(self, release_id: str, table_name: str, count: int) -> bool:
        """Update feature_count for a specific release+table entry."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET feature_count = %s
                        WHERE release_id = %s AND table_name = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (count, release_id, table_name)
                )
                conn.commit()
                return cur.rowcount > 0

    # =========================================================================
    # DELETE
    # =========================================================================

    def delete_for_release(self, release_id: str) -> int:
        """Delete ALL table entries for a release. Returns count deleted."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        DELETE FROM {}.{}
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id,)
                )
                conn.commit()
                count = cur.rowcount
                if count:
                    logger.info(f"Deleted {count} release_table entries for {release_id[:12]}...")
                return count

    # =========================================================================
    # INTERNAL
    # =========================================================================

    def _row_to_model(self, row: dict) -> ReleaseTable:
        """Convert a database row to a ReleaseTable model."""
        return ReleaseTable(
            release_id=row['release_id'],
            table_name=row['table_name'],
            geometry_type=row.get('geometry_type', 'UNKNOWN'),
            feature_count=row.get('feature_count', 0),
            table_role=row.get('table_role', 'primary'),
            table_suffix=row.get('table_suffix'),
            created_at=row.get('created_at', datetime.now(timezone.utc)),
        )
