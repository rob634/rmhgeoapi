"""
Migration: Backfill app.release_tables from existing app.asset_releases.table_name

Run AFTER deploying the new code with `action=ensure` (to create the table),
but BEFORE dropping the table_name column.

Usage:
    conda run -n azgeo python scripts/migrate_release_tables.py
"""
import logging
from infrastructure.database import get_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    """Backfill release_tables from asset_releases.table_name."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Count existing entries
            cur.execute("SELECT COUNT(*) FROM app.release_tables")
            existing = cur.fetchone()[0]
            if existing > 0:
                logger.warning(f"app.release_tables already has {existing} rows. Skipping duplicates.")

            # Backfill: INSERT rows that don't already exist
            cur.execute("""
                INSERT INTO app.release_tables (
                    release_id, table_name, geometry_type,
                    feature_count, table_role, table_suffix, created_at
                )
                SELECT
                    ar.release_id,
                    ar.table_name,
                    COALESCE(tc.geometry_type, 'UNKNOWN'),
                    COALESCE(tc.feature_count, 0),
                    'primary',
                    NULL,
                    ar.created_at
                FROM app.asset_releases ar
                LEFT JOIN geo.table_catalog tc ON tc.table_name = ar.table_name
                WHERE ar.table_name IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM app.release_tables rt
                      WHERE rt.release_id = ar.release_id
                        AND rt.table_name = ar.table_name
                  )
            """)
            migrated = cur.rowcount
            conn.commit()

            logger.info(f"Migrated {migrated} rows to app.release_tables")

            # Verify
            cur.execute("SELECT COUNT(*) FROM app.release_tables")
            total = cur.fetchone()[0]
            logger.info(f"Total rows in app.release_tables: {total}")


if __name__ == '__main__':
    migrate()
