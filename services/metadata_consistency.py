# ============================================================================
# METADATA CONSISTENCY CHECKER
# ============================================================================
# STATUS: Service - Unified metadata consistency enforcement
# PURPOSE: Tier 1 validation of cross-schema metadata integrity
# CREATED: 09 JAN 2026
# EPIC: E7 Pipeline Infrastructure → F7.10 Metadata Consistency
# ============================================================================
"""
Metadata Consistency Checker.

Enforces unified metadata architecture integrity across:
- geo.table_metadata (VectorMetadata)
- app.cog_metadata (RasterMetadata)
- app.dataset_refs (DDH linkage)
- pgstac.items/collections (STAC catalog)

Tier 1 Checks (this service - frequent, lightweight):
- Database cross-reference integrity
- Blob existence via HEAD request
- STAC ↔ Metadata bidirectional linkage

Tier 2 Checks (CoreMachine job - infrequent, thorough):
- Full COG validation (open file, verify overviews)
- Vector row count validation
- STAC spec compliance

This service reports findings but does NOT auto-delete.
Follows GeoOrphanDetector pattern for consistency.

Usage:
    from services.metadata_consistency import get_metadata_consistency_checker

    checker = get_metadata_consistency_checker()
    result = checker.run()

    if result["health_status"] == "ISSUES_DETECTED":
        for issue in result["issues"]:
            print(f"{issue['type']}: {issue['message']}")

Exports:
    MetadataConsistencyChecker: Main checker class
    get_metadata_consistency_checker: Singleton factory
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "MetadataConsistency")


class MetadataConsistencyChecker:
    """
    Unified metadata consistency checker.

    Performs Tier 1 (lightweight) consistency checks across all metadata
    storage locations. Reports findings without making changes.
    """

    def __init__(self):
        """Initialize with lazy-loaded repositories."""
        self._db_repo = None
        self._pgstac_available: Optional[bool] = None
        self._cog_metadata_available: Optional[bool] = None
        self._dataset_refs_available: Optional[bool] = None

    @property
    def db_repo(self):
        """Lazy load database repository."""
        if self._db_repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            self._db_repo = PostgreSQLRepository()
        return self._db_repo

    def run(self) -> Dict[str, Any]:
        """
        Execute all Tier 1 consistency checks.

        Returns:
            Result dict with:
            - success: bool
            - timestamp: ISO timestamp
            - checks: dict of individual check results
            - issues: list of all issues found
            - summary: aggregate metrics
            - health_status: "HEALTHY" or "ISSUES_DETECTED"
            - duration_seconds: execution time
        """
        start_time = datetime.now(timezone.utc)

        result = {
            "success": False,
            "timestamp": start_time.isoformat(),
            "checks": {},
            "issues": [],
            "summary": {
                "total_checks": 0,
                "checks_passed": 0,
                "checks_with_issues": 0,
                "total_issues": 0,
            },
            "health_status": "UNKNOWN",
            "duration_seconds": 0
        }

        try:
            # Run all checks
            checks_to_run = [
                ("stac_vector_orphans", self._check_stac_vector_orphans),
                ("stac_raster_orphans", self._check_stac_raster_orphans),
                ("vector_backlinks", self._check_vector_backlinks),
                ("raster_backlinks", self._check_raster_backlinks),
                ("dataset_refs_vector", self._check_dataset_refs_vector),
                ("dataset_refs_raster", self._check_dataset_refs_raster),
                ("raster_blob_exists", self._check_raster_blobs_exist),
            ]

            for check_name, check_func in checks_to_run:
                logger.info(f"Running check: {check_name}")
                try:
                    check_result = check_func()
                    result["checks"][check_name] = check_result

                    # Aggregate issues
                    if check_result.get("issues"):
                        result["issues"].extend(check_result["issues"])
                        result["summary"]["checks_with_issues"] += 1
                    else:
                        result["summary"]["checks_passed"] += 1

                    result["summary"]["total_checks"] += 1

                except Exception as e:
                    logger.error(f"Check {check_name} failed: {e}")
                    result["checks"][check_name] = {
                        "name": check_name,
                        "error": str(e),
                        "issues": []
                    }
                    result["summary"]["total_checks"] += 1

            # Calculate totals
            result["summary"]["total_issues"] = len(result["issues"])

            # Determine health status
            if result["issues"]:
                result["health_status"] = "ISSUES_DETECTED"
            else:
                result["health_status"] = "HEALTHY"

            result["success"] = True

        except Exception as e:
            logger.error(f"MetadataConsistencyChecker failed: {e}")
            result["error"] = str(e)

        # Calculate duration
        end_time = datetime.now(timezone.utc)
        result["duration_seconds"] = round(
            (end_time - start_time).total_seconds(), 2
        )

        # Log summary
        logger.info(
            f"Metadata consistency check complete: "
            f"{result['summary']['total_checks']} checks, "
            f"{result['summary']['total_issues']} issues, "
            f"status={result['health_status']}"
        )

        return result

    # =========================================================================
    # STAC ORPHAN CHECKS
    # =========================================================================

    def _check_stac_vector_orphans(self) -> Dict[str, Any]:
        """
        Find STAC items for vector collections without geo.table_metadata.

        Checks pgstac.items where collection starts with 'vector-' but
        no corresponding geo.table_metadata record exists.
        """
        check = {
            "name": "stac_vector_orphans",
            "description": "STAC vector items without geo.table_metadata",
            "scanned": 0,
            "issues": []
        }

        if not self._is_pgstac_available():
            check["skipped"] = "pgstac schema not available"
            return check

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if geo.table_metadata exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_metadata'
                        )
                    """)
                    if not cur.fetchone()['exists']:
                        check["skipped"] = "geo.table_metadata not available"
                        return check

                    # Find orphaned STAC items
                    cur.execute("""
                        SELECT i.id as stac_item_id, i.collection
                        FROM pgstac.items i
                        LEFT JOIN geo.table_metadata m
                            ON i.id = m.stac_item_id
                        WHERE i.collection LIKE 'vector-%'
                        AND m.table_name IS NULL
                        LIMIT 100
                    """)
                    orphans = cur.fetchall()
                    check["scanned"] = len(orphans)

                    for orphan in orphans:
                        check["issues"].append({
                            "type": "stac_vector_orphan",
                            "stac_item_id": orphan["stac_item_id"],
                            "collection": orphan["collection"],
                            "message": "STAC item exists but no geo.table_metadata record found"
                        })

        except Exception as e:
            check["error"] = str(e)
            logger.error(f"stac_vector_orphans check failed: {e}")

        return check

    def _check_stac_raster_orphans(self) -> Dict[str, Any]:
        """
        Find STAC items for raster collections without app.cog_metadata.

        Checks pgstac.items where collection does NOT start with 'vector-'
        and no corresponding app.cog_metadata record exists.
        """
        check = {
            "name": "stac_raster_orphans",
            "description": "STAC raster items without app.cog_metadata",
            "scanned": 0,
            "issues": []
        }

        if not self._is_pgstac_available():
            check["skipped"] = "pgstac schema not available"
            return check

        if not self._is_cog_metadata_available():
            check["skipped"] = "app.cog_metadata not available"
            return check

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Find orphaned raster STAC items
                    cur.execute("""
                        SELECT i.id as stac_item_id, i.collection
                        FROM pgstac.items i
                        LEFT JOIN app.cog_metadata c
                            ON i.id = c.stac_item_id
                        WHERE i.collection NOT LIKE 'vector-%'
                        AND c.cog_id IS NULL
                        LIMIT 100
                    """)
                    orphans = cur.fetchall()
                    check["scanned"] = len(orphans)

                    for orphan in orphans:
                        check["issues"].append({
                            "type": "stac_raster_orphan",
                            "stac_item_id": orphan["stac_item_id"],
                            "collection": orphan["collection"],
                            "message": "STAC item exists but no app.cog_metadata record found"
                        })

        except Exception as e:
            check["error"] = str(e)
            logger.error(f"stac_raster_orphans check failed: {e}")

        return check

    # =========================================================================
    # BACKLINK CHECKS
    # =========================================================================

    def _check_vector_backlinks(self) -> Dict[str, Any]:
        """
        Find geo.table_metadata with stac_item_id that doesn't exist in pgstac.

        Detects broken backlinks where metadata points to deleted STAC items.
        """
        check = {
            "name": "vector_backlinks",
            "description": "geo.table_metadata with broken STAC backlinks",
            "scanned": 0,
            "issues": []
        }

        if not self._is_pgstac_available():
            check["skipped"] = "pgstac schema not available"
            return check

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if geo.table_metadata exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_metadata'
                        )
                    """)
                    if not cur.fetchone()['exists']:
                        check["skipped"] = "geo.table_metadata not available"
                        return check

                    # Find broken backlinks
                    cur.execute("""
                        SELECT m.table_name, m.stac_item_id, m.stac_collection_id
                        FROM geo.table_metadata m
                        LEFT JOIN pgstac.items i ON m.stac_item_id = i.id
                        WHERE m.stac_item_id IS NOT NULL
                        AND i.id IS NULL
                        LIMIT 100
                    """)
                    broken = cur.fetchall()
                    check["scanned"] = len(broken)

                    for row in broken:
                        check["issues"].append({
                            "type": "vector_backlink_broken",
                            "table_name": row["table_name"],
                            "stac_item_id": row["stac_item_id"],
                            "stac_collection_id": row["stac_collection_id"],
                            "message": "table_metadata.stac_item_id points to non-existent STAC item"
                        })

        except Exception as e:
            check["error"] = str(e)
            logger.error(f"vector_backlinks check failed: {e}")

        return check

    def _check_raster_backlinks(self) -> Dict[str, Any]:
        """
        Find app.cog_metadata with stac_item_id that doesn't exist in pgstac.

        Detects broken backlinks where COG metadata points to deleted STAC items.
        """
        check = {
            "name": "raster_backlinks",
            "description": "app.cog_metadata with broken STAC backlinks",
            "scanned": 0,
            "issues": []
        }

        if not self._is_pgstac_available():
            check["skipped"] = "pgstac schema not available"
            return check

        if not self._is_cog_metadata_available():
            check["skipped"] = "app.cog_metadata not available"
            return check

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Find broken backlinks
                    cur.execute("""
                        SELECT c.cog_id, c.stac_item_id, c.stac_collection_id
                        FROM app.cog_metadata c
                        LEFT JOIN pgstac.items i ON c.stac_item_id = i.id
                        WHERE c.stac_item_id IS NOT NULL
                        AND i.id IS NULL
                        LIMIT 100
                    """)
                    broken = cur.fetchall()
                    check["scanned"] = len(broken)

                    for row in broken:
                        check["issues"].append({
                            "type": "raster_backlink_broken",
                            "cog_id": row["cog_id"],
                            "stac_item_id": row["stac_item_id"],
                            "stac_collection_id": row["stac_collection_id"],
                            "message": "cog_metadata.stac_item_id points to non-existent STAC item"
                        })

        except Exception as e:
            check["error"] = str(e)
            logger.error(f"raster_backlinks check failed: {e}")

        return check

    # =========================================================================
    # DATASET REFS INTEGRITY CHECKS
    # =========================================================================

    def _check_dataset_refs_vector(self) -> Dict[str, Any]:
        """
        Find app.dataset_refs for vectors that don't exist in geo.table_metadata.

        Detects orphaned DDH linkage records.
        """
        check = {
            "name": "dataset_refs_vector",
            "description": "dataset_refs for non-existent vector tables",
            "scanned": 0,
            "issues": []
        }

        if not self._is_dataset_refs_available():
            check["skipped"] = "app.dataset_refs not available"
            return check

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if geo.table_metadata exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_metadata'
                        )
                    """)
                    if not cur.fetchone()['exists']:
                        check["skipped"] = "geo.table_metadata not available"
                        return check

                    # Find orphaned refs
                    cur.execute("""
                        SELECT r.dataset_id, r.ddh_dataset_id, r.ddh_resource_id
                        FROM app.dataset_refs r
                        LEFT JOIN geo.table_metadata m ON r.dataset_id = m.table_name
                        WHERE r.data_type = 'vector'
                        AND m.table_name IS NULL
                        LIMIT 100
                    """)
                    orphans = cur.fetchall()
                    check["scanned"] = len(orphans)

                    for row in orphans:
                        check["issues"].append({
                            "type": "dataset_refs_vector_orphan",
                            "dataset_id": row["dataset_id"],
                            "ddh_dataset_id": row["ddh_dataset_id"],
                            "ddh_resource_id": row["ddh_resource_id"],
                            "message": "dataset_refs points to non-existent vector table"
                        })

        except Exception as e:
            check["error"] = str(e)
            logger.error(f"dataset_refs_vector check failed: {e}")

        return check

    def _check_dataset_refs_raster(self) -> Dict[str, Any]:
        """
        Find app.dataset_refs for rasters that don't exist in app.cog_metadata.

        Detects orphaned DDH linkage records.
        """
        check = {
            "name": "dataset_refs_raster",
            "description": "dataset_refs for non-existent raster COGs",
            "scanned": 0,
            "issues": []
        }

        if not self._is_dataset_refs_available():
            check["skipped"] = "app.dataset_refs not available"
            return check

        if not self._is_cog_metadata_available():
            check["skipped"] = "app.cog_metadata not available"
            return check

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Find orphaned refs
                    cur.execute("""
                        SELECT r.dataset_id, r.ddh_dataset_id, r.ddh_resource_id
                        FROM app.dataset_refs r
                        LEFT JOIN app.cog_metadata c ON r.dataset_id = c.cog_id
                        WHERE r.data_type = 'raster'
                        AND c.cog_id IS NULL
                        LIMIT 100
                    """)
                    orphans = cur.fetchall()
                    check["scanned"] = len(orphans)

                    for row in orphans:
                        check["issues"].append({
                            "type": "dataset_refs_raster_orphan",
                            "dataset_id": row["dataset_id"],
                            "ddh_dataset_id": row["ddh_dataset_id"],
                            "ddh_resource_id": row["ddh_resource_id"],
                            "message": "dataset_refs points to non-existent COG"
                        })

        except Exception as e:
            check["error"] = str(e)
            logger.error(f"dataset_refs_raster check failed: {e}")

        return check

    # =========================================================================
    # BLOB EXISTENCE CHECKS
    # =========================================================================

    def _check_raster_blobs_exist(self) -> Dict[str, Any]:
        """
        Verify COGs in app.cog_metadata actually exist in blob storage.

        Uses HEAD request only (cheap operation).
        Checks most recent 100 COGs to catch recent issues.
        """
        check = {
            "name": "raster_blob_exists",
            "description": "COG metadata with missing blob files",
            "scanned": 0,
            "issues": []
        }

        if not self._is_cog_metadata_available():
            check["skipped"] = "app.cog_metadata not available"
            return check

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Get recent COG records
                    cur.execute("""
                        SELECT cog_id, container, blob_path
                        FROM app.cog_metadata
                        ORDER BY created_at DESC
                        LIMIT 100
                    """)
                    cogs = cur.fetchall()

            check["scanned"] = len(cogs)

            # Check each blob exists (HEAD only)
            for cog in cogs:
                try:
                    exists = self._blob_exists(cog["container"], cog["blob_path"])
                    if not exists:
                        check["issues"].append({
                            "type": "raster_blob_missing",
                            "cog_id": cog["cog_id"],
                            "container": cog["container"],
                            "blob_path": cog["blob_path"],
                            "message": "COG metadata exists but blob not found in storage"
                        })
                except Exception as e:
                    # Log but don't fail entire check
                    logger.warning(
                        f"Could not verify blob {cog['container']}/{cog['blob_path']}: {e}"
                    )

        except Exception as e:
            check["error"] = str(e)
            logger.error(f"raster_blob_exists check failed: {e}")

        return check

    def _blob_exists(self, container: str, blob_path: str) -> bool:
        """
        Check if blob exists using HEAD request (cheap operation).

        Args:
            container: Azure storage container name
            blob_path: Path within container

        Returns:
            True if blob exists, False otherwise
        """
        try:
            from infrastructure.blob_storage import BlobStorageRepository
            repo = BlobStorageRepository(container)
            return repo.blob_exists(blob_path)
        except Exception as e:
            logger.debug(f"Blob existence check failed for {container}/{blob_path}: {e}")
            return False  # Assume missing on error

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _is_pgstac_available(self) -> bool:
        """Check if pgstac schema is available."""
        if self._pgstac_available is not None:
            return self._pgstac_available

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.schemata
                            WHERE schema_name = 'pgstac'
                        )
                    """)
                    self._pgstac_available = cur.fetchone()['exists']
        except Exception:
            self._pgstac_available = False

        return self._pgstac_available

    def _is_cog_metadata_available(self) -> bool:
        """Check if app.cog_metadata table is available."""
        if self._cog_metadata_available is not None:
            return self._cog_metadata_available

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'app' AND table_name = 'cog_metadata'
                        )
                    """)
                    self._cog_metadata_available = cur.fetchone()['exists']
        except Exception:
            self._cog_metadata_available = False

        return self._cog_metadata_available

    def _is_dataset_refs_available(self) -> bool:
        """Check if app.dataset_refs table is available."""
        if self._dataset_refs_available is not None:
            return self._dataset_refs_available

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'app' AND table_name = 'dataset_refs'
                        )
                    """)
                    self._dataset_refs_available = cur.fetchone()['exists']
        except Exception:
            self._dataset_refs_available = False

        return self._dataset_refs_available


# =============================================================================
# SINGLETON FACTORY
# =============================================================================

_instance: Optional[MetadataConsistencyChecker] = None


def get_metadata_consistency_checker() -> MetadataConsistencyChecker:
    """Get singleton MetadataConsistencyChecker instance."""
    global _instance
    if _instance is None:
        _instance = MetadataConsistencyChecker()
    return _instance


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'MetadataConsistencyChecker',
    'get_metadata_consistency_checker',
]
