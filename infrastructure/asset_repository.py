# ============================================================================
# CLAUDE CONTEXT - ASSET REPOSITORY (SIMPLIFIED CONTAINER CRUD)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Infrastructure - V0.9 Asset entity CRUD
# PURPOSE: Database operations for app.assets table (stable identity container)
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: AssetRepository
# DEPENDENCIES: psycopg, core.models.asset
# ============================================================================
"""
Asset Repository -- Simplified Container CRUD.

Database operations for the V0.9 Asset entity (stable identity container).
This is intentionally much simpler than the V0.8 GeospatialAssetRepository
because the Asset entity only has ~12 fields -- all versioned content, approval
state, and processing lifecycle have moved to AssetRelease.

Features:
    - CRUD for app.assets table
    - Advisory locks for concurrent find_or_create serialization
    - Soft delete with audit trail
    - Release count tracking

Exports:
    AssetRepository: CRUD operations for V0.9 assets

Created: 21 FEB 2026 as part of V0.9 Asset/Release entity split
"""

import hashlib
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from core.models.asset import Asset
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "AssetRepository")


class AssetRepository(PostgreSQLRepository):
    """
    Repository for V0.9 Asset operations.

    Handles CRUD operations for app.assets table (stable identity container).
    Uses advisory locks for concurrent find_or_create serialization.

    Table: app.assets
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "assets"
        self.schema = "app"

    # =========================================================================
    # CREATE
    # =========================================================================

    def create(self, asset: Asset) -> Asset:
        """
        Insert a new Asset record.

        Uses RETURNING * to return the created row as an Asset model.
        The psycopg3 type adapters handle dict->JSONB and Enum->.value
        automatically -- no manual json.dumps() or .value needed.

        Args:
            asset: Asset model to insert

        Returns:
            Created Asset with database-assigned timestamps

        Raises:
            psycopg.errors.UniqueViolation: If asset_id already exists
        """
        logger.info(f"Creating asset: {asset.asset_id} "
                     f"(platform={asset.platform_id}, dataset={asset.dataset_id}, "
                     f"resource={asset.resource_id})")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            asset_id, platform_id, dataset_id, resource_id,
                            platform_refs, data_type, release_count,
                            created_at, updated_at,
                            deleted_at, deleted_by
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s
                        )
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        asset.asset_id, asset.platform_id, asset.dataset_id,
                        asset.resource_id, asset.platform_refs, asset.data_type,
                        asset.release_count,
                        asset.created_at, asset.updated_at,
                        asset.deleted_at, asset.deleted_by
                    )
                )
                row = cur.fetchone()
                conn.commit()

                logger.info(f"Created asset: {asset.asset_id}")
                return self._row_to_model(row)

    # =========================================================================
    # READ
    # =========================================================================

    def get_by_id(self, asset_id: str) -> Optional[Asset]:
        """
        Get an asset by primary key (includes soft-deleted).

        Args:
            asset_id: Asset identifier (deterministic SHA256)

        Returns:
            Asset if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE asset_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id,)
                )
                row = cur.fetchone()
                if not row:
                    return None
                return self._row_to_model(row)

    def get_by_identity(
        self,
        platform_id: str,
        dataset_id: str,
        resource_id: str
    ) -> Optional[Asset]:
        """
        Get an active asset by its identity triple.

        Only returns non-deleted assets. The identity triple
        (platform_id, dataset_id, resource_id) has a unique partial index
        WHERE deleted_at IS NULL, so at most one row will match.

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            dataset_id: Dataset identifier
            resource_id: Resource identifier

        Returns:
            Asset if found and active, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE platform_id = %s
                          AND dataset_id = %s
                          AND resource_id = %s
                          AND deleted_at IS NULL
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (platform_id, dataset_id, resource_id)
                )
                row = cur.fetchone()
                if not row:
                    return None
                return self._row_to_model(row)

    # =========================================================================
    # FIND OR CREATE (with advisory lock)
    # =========================================================================

    def find_or_create(
        self,
        platform_id: str,
        dataset_id: str,
        resource_id: str,
        data_type: str
    ) -> Tuple[Asset, str]:
        """
        Find an existing active asset or create a new one.

        Uses pg_advisory_xact_lock to serialize concurrent calls for the
        same identity triple. The advisory lock is scoped to the transaction
        and released automatically on commit/rollback.

        Lock key: first 15 hex chars of MD5(platform_id|dataset_id|resource_id)
        converted to int8. 15 hex chars fit safely in PostgreSQL's bigint range.

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            dataset_id: Dataset identifier
            resource_id: Resource identifier
            data_type: "raster" or "vector"

        Returns:
            Tuple of (Asset, operation) where operation is "existing" or "created"
        """
        identity_key = f"{platform_id}|{dataset_id}|{resource_id}"
        lock_hash = int(
            hashlib.md5(identity_key.encode()).hexdigest()[:15], 16
        )

        logger.info(f"find_or_create: {identity_key} (lock={lock_hash})")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Acquire advisory lock scoped to this transaction
                cur.execute(
                    sql.SQL("SELECT pg_advisory_xact_lock(%s)"),
                    (lock_hash,)
                )

                # Check for existing active asset
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE platform_id = %s
                          AND dataset_id = %s
                          AND resource_id = %s
                          AND deleted_at IS NULL
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (platform_id, dataset_id, resource_id)
                )
                row = cur.fetchone()

                if row:
                    conn.commit()
                    asset = self._row_to_model(row)
                    logger.info(f"find_or_create: existing asset {asset.asset_id}")
                    return asset, "existing"

                # Create new asset
                asset_id = Asset.generate_asset_id(
                    platform_id, dataset_id, resource_id
                )
                now = datetime.now(timezone.utc)

                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            asset_id, platform_id, dataset_id, resource_id,
                            platform_refs, data_type, release_count,
                            created_at, updated_at,
                            deleted_at, deleted_by
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s
                        )
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        asset_id, platform_id, dataset_id, resource_id,
                        {},  # platform_refs default empty dict
                        data_type, 0,  # release_count starts at 0
                        now, now,
                        None, None  # not deleted
                    )
                )
                row = cur.fetchone()
                conn.commit()

                asset = self._row_to_model(row)
                logger.info(f"find_or_create: created asset {asset.asset_id}")
                return asset, "created"

    # =========================================================================
    # UPDATE
    # =========================================================================

    def soft_delete(self, asset_id: str, deleted_by: str) -> bool:
        """
        Soft-delete an asset by setting deleted_at and deleted_by.

        Only deletes if the asset exists and is not already deleted.

        Args:
            asset_id: Asset identifier
            deleted_by: Who is performing the deletion (audit trail)

        Returns:
            True if asset was deleted, False if not found or already deleted
        """
        logger.info(f"Soft-deleting asset: {asset_id} (by={deleted_by})")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET deleted_at = %s,
                            deleted_by = %s,
                            updated_at = %s
                        WHERE asset_id = %s
                          AND deleted_at IS NULL
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        datetime.now(timezone.utc),
                        deleted_by,
                        datetime.now(timezone.utc),
                        asset_id
                    )
                )
                updated = cur.rowcount > 0
                conn.commit()

                if updated:
                    logger.info(f"Soft-deleted asset: {asset_id}")
                else:
                    logger.info(f"Soft-delete no-op: {asset_id} (not found or already deleted)")

                return updated

    def increment_release_count(self, asset_id: str) -> bool:
        """
        Increment the release_count for an asset.

        Called when a new Release is created under this Asset.

        Args:
            asset_id: Asset identifier

        Returns:
            True if updated, False if asset not found
        """
        logger.info(f"Incrementing release count: {asset_id}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET release_count = release_count + 1,
                            updated_at = %s
                        WHERE asset_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (datetime.now(timezone.utc), asset_id)
                )
                updated = cur.rowcount > 0
                conn.commit()

                if updated:
                    logger.info(f"Incremented release count: {asset_id}")
                else:
                    logger.info(f"Increment release count no-op: {asset_id} (not found)")

                return updated

    # =========================================================================
    # LIST
    # =========================================================================

    def list_active(self, limit: int = 100) -> List[Asset]:
        """
        List active (non-deleted) assets, most recent first.

        Args:
            limit: Maximum number of assets to return (default 100)

        Returns:
            List of active Asset models
        """
        logger.info(f"Listing active assets (limit={limit})")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE deleted_at IS NULL
                        ORDER BY created_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (limit,)
                )
                rows = cur.fetchall()

                logger.info(f"Listed {len(rows)} active assets")
                return [self._row_to_model(row) for row in rows]

    # =========================================================================
    # ROW MAPPING
    # =========================================================================

    def _row_to_model(self, row: Dict[str, Any]) -> Asset:
        """
        Convert a database row dict to an Asset model.

        psycopg3 with dict_row cursor returns column names as keys.
        JSONB columns are automatically deserialized to Python dicts.
        Datetime columns are automatically deserialized to Python datetimes.

        Args:
            row: Dict from psycopg3 dict_row cursor

        Returns:
            Asset model instance
        """
        return Asset(
            asset_id=row['asset_id'],
            platform_id=row.get('platform_id', 'ddh'),
            dataset_id=row['dataset_id'],
            resource_id=row['resource_id'],
            platform_refs=row.get('platform_refs', {}),
            data_type=row['data_type'],
            release_count=row.get('release_count', 0),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at'),
            deleted_at=row.get('deleted_at'),
            deleted_by=row.get('deleted_by'),
        )
