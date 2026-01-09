# ============================================================================
# DATASET REFS REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Cross-type DDH linkage persistence
# PURPOSE: Write/read app.dataset_refs for DDH integration
# CREATED: 09 JAN 2026
# EPIC: E7 Pipeline Infrastructure → F7.8 Unified Metadata Architecture
# ============================================================================
"""
Dataset Refs Repository.

Provides persistence for app.dataset_refs table which links internal
dataset identifiers (table names, COG paths) to external DDH identifiers.

This is a cross-type table - it can store refs for vector, raster, or zarr
datasets using the data_type field to distinguish.

Usage:
    from infrastructure.dataset_refs_repository import DatasetRefsRepository

    repo = DatasetRefsRepository()
    repo.upsert_ref(
        dataset_id="admin_boundaries_chile",
        data_type="vector",
        ddh_dataset_id="chile-admin",
        ddh_resource_id="res-001"
    )

Exports:
    DatasetRefsRepository: Repository for app.dataset_refs CRUD
    get_dataset_refs_repository: Singleton factory
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from infrastructure.postgresql import PostgreSQLRepository

logger = logging.getLogger(__name__)


class DatasetRefsRepository:
    """
    Repository for app.dataset_refs table.

    Provides upsert and lookup operations for DDH linkage records.
    Gracefully handles missing table (logs warning, returns None).
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        self._pg_repo = PostgreSQLRepository()
        self._table_exists: Optional[bool] = None

    def _check_table_exists(self) -> bool:
        """
        Check if app.dataset_refs table exists.

        Caches result to avoid repeated checks.
        """
        if self._table_exists is not None:
            return self._table_exists

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'app'
                            AND table_name = 'dataset_refs'
                        ) as table_exists
                    """)
                    result = cur.fetchone()
                    self._table_exists = result['table_exists'] if result else False

                    if not self._table_exists:
                        logger.warning(
                            "app.dataset_refs table does not exist. "
                            "Run schema rebuild to create it."
                        )
                    return self._table_exists

        except Exception as e:
            logger.error(f"Error checking dataset_refs table: {e}")
            self._table_exists = False
            return False

    def upsert_ref(
        self,
        dataset_id: str,
        data_type: str,
        ddh_dataset_id: Optional[str] = None,
        ddh_resource_id: Optional[str] = None,
        ddh_version_id: Optional[str] = None,
        other_refs: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Insert or update dataset reference.

        Uses PostgreSQL UPSERT (INSERT ON CONFLICT UPDATE) for idempotency.

        Args:
            dataset_id: Internal dataset identifier (table name, COG path)
            data_type: Dataset type ('vector', 'raster', 'zarr')
            ddh_dataset_id: DDH dataset identifier
            ddh_resource_id: DDH resource identifier
            ddh_version_id: DDH version identifier
            other_refs: Additional external system refs (JSONB)

        Returns:
            True if successful, False if table doesn't exist or error
        """
        if not self._check_table_exists():
            logger.debug(f"Skipping dataset_refs upsert - table not available")
            return False

        # Skip if no DDH refs provided
        if not any([ddh_dataset_id, ddh_resource_id, ddh_version_id]):
            logger.debug(f"Skipping dataset_refs upsert - no DDH refs for {dataset_id}")
            return False

        try:
            import json
            other_refs_json = json.dumps(other_refs or {})
            now = datetime.now(timezone.utc)

            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO app.dataset_refs (
                            dataset_id, data_type,
                            ddh_dataset_id, ddh_resource_id, ddh_version_id,
                            other_refs, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (dataset_id, data_type) DO UPDATE SET
                            ddh_dataset_id = EXCLUDED.ddh_dataset_id,
                            ddh_resource_id = EXCLUDED.ddh_resource_id,
                            ddh_version_id = EXCLUDED.ddh_version_id,
                            other_refs = EXCLUDED.other_refs,
                            updated_at = EXCLUDED.updated_at
                    """, (
                        dataset_id, data_type,
                        ddh_dataset_id, ddh_resource_id, ddh_version_id,
                        other_refs_json, now, now
                    ))
                    conn.commit()

            logger.info(
                f"Upserted dataset_refs: {dataset_id} ({data_type}) "
                f"→ DDH:{ddh_dataset_id or 'none'}"
            )
            return True

        except Exception as e:
            logger.error(f"Error upserting dataset_refs for {dataset_id}: {e}")
            return False

    def get_ref(
        self,
        dataset_id: str,
        data_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get dataset reference by internal ID and type.

        Args:
            dataset_id: Internal dataset identifier
            data_type: Dataset type ('vector', 'raster', 'zarr')

        Returns:
            Dict with ref data, or None if not found
        """
        if not self._check_table_exists():
            return None

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM app.dataset_refs
                        WHERE dataset_id = %s AND data_type = %s
                    """, (dataset_id, data_type))
                    result = cur.fetchone()
                    return dict(result) if result else None

        except Exception as e:
            logger.error(f"Error getting dataset_ref for {dataset_id}: {e}")
            return None

    def get_by_ddh_id(
        self,
        ddh_dataset_id: str
    ) -> list[Dict[str, Any]]:
        """
        Find all datasets linked to a DDH dataset ID.

        Args:
            ddh_dataset_id: DDH dataset identifier

        Returns:
            List of matching refs (may include vector, raster, zarr)
        """
        if not self._check_table_exists():
            return []

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM app.dataset_refs
                        WHERE ddh_dataset_id = %s
                        ORDER BY data_type, dataset_id
                    """, (ddh_dataset_id,))
                    return [dict(row) for row in cur.fetchall()]

        except Exception as e:
            logger.error(f"Error finding refs for DDH:{ddh_dataset_id}: {e}")
            return []


# Singleton instance
_instance: Optional[DatasetRefsRepository] = None


def get_dataset_refs_repository() -> DatasetRefsRepository:
    """Get singleton DatasetRefsRepository instance."""
    global _instance
    if _instance is None:
        _instance = DatasetRefsRepository()
    return _instance


__all__ = ['DatasetRefsRepository', 'get_dataset_refs_repository']
