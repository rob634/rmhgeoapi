# ============================================================================
# GEO ORPHAN DETECTOR
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - Geo schema orphan detection
# PURPOSE: Detect orphaned tables and metadata in geo schema
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: GeoOrphanDetector, geo_orphan_detector
# DEPENDENCIES: infrastructure.factory
# ============================================================================
"""
Geo Orphan Detector.

Detects orphaned tables and metadata in the geo schema.
Extracted from janitor_service.py during SystemGuardian refactor (14 MAR 2026).

Exports:
    GeoOrphanDetector: Orphan detection class
    geo_orphan_detector: Singleton instance
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from psycopg import sql

logger = logging.getLogger(__name__)


class GeoOrphanDetector:
    """
    Detect orphaned tables and metadata in geo schema.

    Detects two types of orphans:
    1. Orphaned Tables: Tables in geo schema without metadata records
    2. Orphaned Metadata: Metadata records for non-existent tables

    Does NOT automatically delete - reports findings for manual review.

    Usage:
        detector = GeoOrphanDetector()
        result = detector.run()

        if result['orphaned_tables']:
            print(f"Found {len(result['orphaned_tables'])} orphaned tables")
    """

    def __init__(self):
        """Initialize with lazy repository loading."""
        self._db_repo = None

    @property
    def db_repo(self):
        """Lazy load database repository."""
        if self._db_repo is None:
            from infrastructure.factory import RepositoryFactory
            repos = RepositoryFactory.create_repositories()
            self._db_repo = repos['job_repo']
        return self._db_repo

    def run(self) -> Dict[str, Any]:
        """
        Run orphan detection and return report.

        Returns:
            Dict with orphaned tables, orphaned metadata, and summary.
        """
        start_time = datetime.now(timezone.utc)

        result = {
            "success": False,
            "timestamp": start_time.isoformat(),
            "orphaned_tables": [],
            "orphaned_metadata": [],
            "tracked_tables": [],
            "summary": {}
        }

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Step 1: Get all tables in geo schema (excluding system tables)
                    cur.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'geo'
                        AND table_type = 'BASE TABLE'
                        AND table_name NOT IN ('table_catalog', 'table_metadata', 'feature_collection_styles')
                        ORDER BY table_name
                    """)
                    geo_tables = set(row['table_name'] for row in cur.fetchall())

                    # Step 2: Check if table_catalog exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_catalog'
                        )
                    """)
                    catalog_table_exists = cur.fetchone()['exists']

                    if not catalog_table_exists:
                        logger.warning("GeoOrphanDetector: geo.table_catalog does not exist!")
                        for table_name in sorted(geo_tables):
                            try:
                                cur.execute(sql.SQL('SELECT COUNT(*) FROM {}.{}').format(
                                    sql.Identifier('geo'), sql.Identifier(table_name)
                                ))
                                row_count = cur.fetchone()['count']
                            except Exception:
                                row_count = None

                            result["orphaned_tables"].append({
                                "table_name": table_name,
                                "row_count": row_count,
                                "reason": "Table exists but geo.table_catalog does not exist"
                            })

                        result["summary"] = {
                            "total_geo_tables": len(geo_tables),
                            "total_catalog_records": 0,
                            "tracked": 0,
                            "orphaned_tables": len(geo_tables),
                            "orphaned_catalog": 0,
                            "health_status": "ORPHANS_DETECTED" if geo_tables else "HEALTHY",
                            "catalog_table_missing": True
                        }
                        result["success"] = True
                        result["duration_seconds"] = round(
                            (datetime.now(timezone.utc) - start_time).total_seconds(), 2
                        )
                        return result

                    # Step 3: Get all table names in catalog
                    cur.execute("""
                        SELECT table_name, created_at
                        FROM geo.table_catalog
                        ORDER BY table_name
                    """)
                    catalog_tables = {}
                    for row in cur.fetchall():
                        catalog_tables[row['table_name']] = {
                            'created_at': row['created_at'].isoformat() if row.get('created_at') else None
                        }

                    catalog_names = set(catalog_tables.keys())

                    # Step 4: Identify orphans
                    orphaned_tables = geo_tables - catalog_names
                    for table_name in sorted(orphaned_tables):
                        try:
                            cur.execute(sql.SQL('SELECT COUNT(*) FROM {}.{}').format(
                                sql.Identifier('geo'), sql.Identifier(table_name)
                            ))
                            row_count = cur.fetchone()['count']
                        except Exception:
                            row_count = None

                        result["orphaned_tables"].append({
                            "table_name": table_name,
                            "row_count": row_count,
                            "reason": "Table exists in geo schema but has no catalog record"
                        })

                    orphaned_catalog = catalog_names - geo_tables
                    for table_name in sorted(orphaned_catalog):
                        cat = catalog_tables[table_name]
                        result["orphaned_metadata"].append({
                            "table_name": table_name,
                            "created_at": cat['created_at'],
                            "reason": "Catalog entry exists but table was dropped"
                        })

                    tracked = geo_tables & catalog_names
                    result["tracked_tables"] = sorted(tracked)

            # Build summary
            result["summary"] = {
                "total_geo_tables": len(geo_tables),
                "total_catalog_records": len(catalog_tables),
                "tracked": len(result["tracked_tables"]),
                "orphaned_tables": len(result["orphaned_tables"]),
                "orphaned_catalog": len(result["orphaned_metadata"]),
                "health_status": "HEALTHY" if not result["orphaned_tables"] and not result["orphaned_metadata"] else "ORPHANS_DETECTED"
            }

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            result["duration_seconds"] = round(duration, 2)
            result["success"] = True

            if result["orphaned_tables"]:
                logger.warning(
                    f"GeoOrphanDetector: Found {len(result['orphaned_tables'])} orphaned tables: "
                    f"{[t['table_name'] for t in result['orphaned_tables']]}"
                )
            if result["orphaned_metadata"]:
                logger.warning(
                    f"GeoOrphanDetector: Found {len(result['orphaned_metadata'])} orphaned metadata records: "
                    f"{[m['table_name'] for m in result['orphaned_metadata']]}"
                )
            if not result["orphaned_tables"] and not result["orphaned_metadata"]:
                logger.info(
                    f"GeoOrphanDetector: All {len(result['tracked_tables'])} geo tables are tracked"
                )

            return result

        except Exception as e:
            logger.error(f"GeoOrphanDetector failed: {e}")
            result["error"] = str(e)
            result["duration_seconds"] = round(
                (datetime.now(timezone.utc) - start_time).total_seconds(), 2
            )
            return result


# Singleton instance for easy import
geo_orphan_detector = GeoOrphanDetector()


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = ['GeoOrphanDetector', 'geo_orphan_detector']
