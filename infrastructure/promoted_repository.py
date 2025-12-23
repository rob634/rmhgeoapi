# ============================================================================
# CLAUDE CONTEXT - PROMOTED DATASET REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Repository - Database operations for promoted datasets
# PURPOSE: CRUD operations for app.promoted_datasets table
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: PromotedDatasetRepository
# DEPENDENCIES: psycopg, core.models.promoted
# ============================================================================
"""
Promoted Dataset Repository.

Database operations for the promoted dataset system. Handles all persistence
for the promoted_datasets registry.

Exports:
    PromotedDatasetRepository: CRUD operations for promoted datasets

Created: 22 DEC 2025
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import logging

from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from core.models import PromotedDataset
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "PromotedRepository")


class PromotedDatasetRepository(PostgreSQLRepository):
    """
    Repository for promoted dataset operations.

    Handles CRUD operations for app.promoted_datasets table.
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "promoted_datasets"
        self.schema = "app"

    # =========================================================================
    # CREATE
    # =========================================================================

    def create(self, dataset: PromotedDataset) -> PromotedDataset:
        """
        Create a new promoted dataset entry.

        Args:
            dataset: PromotedDataset model to insert

        Returns:
            Created PromotedDataset with timestamps

        Raises:
            ValueError: If promoted_id already exists
        """
        logger.info(f"Creating promoted dataset: {dataset.promoted_id}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if already exists
                cur.execute(
                    sql.SQL("SELECT 1 FROM {}.{} WHERE promoted_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (dataset.promoted_id,)
                )
                if cur.fetchone():
                    raise ValueError(f"Promoted dataset '{dataset.promoted_id}' already exists")

                # Insert
                now = datetime.now(timezone.utc)
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            promoted_id,
                            stac_collection_id, stac_item_id,
                            title, description,
                            thumbnail_url, thumbnail_generated_at,
                            tags, viewer_config, style_id,
                            in_gallery, gallery_order,
                            promoted_at, updated_at
                        ) VALUES (
                            %s,
                            %s, %s,
                            %s, %s,
                            %s, %s,
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
                        dataset.promoted_id,
                        dataset.stac_collection_id, dataset.stac_item_id,
                        dataset.title, dataset.description,
                        dataset.thumbnail_url, dataset.thumbnail_generated_at,
                        dataset.tags, dataset.viewer_config, dataset.style_id,
                        dataset.in_gallery, dataset.gallery_order,
                        now, now
                    )
                )
                row = cur.fetchone()
                conn.commit()

                logger.info(f"Created promoted dataset: {dataset.promoted_id}")
                return self._row_to_model(row)

    # =========================================================================
    # READ
    # =========================================================================

    def get_by_id(self, promoted_id: str) -> Optional[PromotedDataset]:
        """
        Get a promoted dataset by ID.

        Args:
            promoted_id: Promoted dataset identifier

        Returns:
            PromotedDataset if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE promoted_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (promoted_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_stac_collection(self, stac_collection_id: str) -> Optional[PromotedDataset]:
        """
        Get a promoted dataset by STAC collection ID.

        Args:
            stac_collection_id: STAC collection identifier

        Returns:
            PromotedDataset if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE stac_collection_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (stac_collection_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_stac_item(self, stac_item_id: str) -> Optional[PromotedDataset]:
        """
        Get a promoted dataset by STAC item ID.

        Args:
            stac_item_id: STAC item identifier

        Returns:
            PromotedDataset if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE stac_item_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (stac_item_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def list_all(self) -> List[PromotedDataset]:
        """
        List all promoted datasets.

        Returns:
            List of PromotedDataset models, ordered by promoted_at DESC
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} ORDER BY promoted_at DESC").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    )
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_gallery(self) -> List[PromotedDataset]:
        """
        List gallery items (in_gallery=True), ordered by gallery_order.

        Returns:
            List of PromotedDataset models in gallery order
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE in_gallery = TRUE
                        ORDER BY gallery_order ASC NULLS LAST, promoted_at DESC
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    )
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    # =========================================================================
    # UPDATE
    # =========================================================================

    def update(self, promoted_id: str, updates: Dict[str, Any]) -> Optional[PromotedDataset]:
        """
        Update a promoted dataset.

        Args:
            promoted_id: Dataset to update
            updates: Dictionary of field updates

        Returns:
            Updated PromotedDataset if found, None otherwise
        """
        if not updates:
            return self.get_by_id(promoted_id)

        # Always update updated_at
        updates['updated_at'] = datetime.now(timezone.utc)

        # Build SET clause
        set_parts = []
        values = []
        for key, value in updates.items():
            set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            values.append(value)

        values.append(promoted_id)  # For WHERE clause

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("UPDATE {}.{} SET {} WHERE promoted_id = %s RETURNING *").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.SQL(", ").join(set_parts)
                    ),
                    values
                )
                row = cur.fetchone()
                conn.commit()

                return self._row_to_model(row) if row else None

    # =========================================================================
    # GALLERY OPERATIONS
    # =========================================================================

    def add_to_gallery(self, promoted_id: str, order: Optional[int] = None) -> Optional[PromotedDataset]:
        """
        Add a promoted dataset to the gallery.

        Args:
            promoted_id: Dataset to add to gallery
            order: Optional gallery order (auto-assigned if not provided)

        Returns:
            Updated PromotedDataset if found, None otherwise
        """
        # If no order specified, get next available order
        if order is None:
            order = self._get_next_gallery_order()

        return self.update(promoted_id, {
            'in_gallery': True,
            'gallery_order': order
        })

    def remove_from_gallery(self, promoted_id: str) -> Optional[PromotedDataset]:
        """
        Remove a promoted dataset from the gallery (keep promoted).

        Args:
            promoted_id: Dataset to remove from gallery

        Returns:
            Updated PromotedDataset if found, None otherwise
        """
        return self.update(promoted_id, {
            'in_gallery': False,
            'gallery_order': None
        })

    def _get_next_gallery_order(self) -> int:
        """Get the next available gallery order number."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT COALESCE(MAX(gallery_order), 0) + 1
                        FROM {}.{}
                        WHERE in_gallery = TRUE
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    )
                )
                row = cur.fetchone()
                return row['coalesce'] if row else 1

    # =========================================================================
    # DELETE (DEMOTE)
    # =========================================================================

    def delete(self, promoted_id: str) -> bool:
        """
        Delete (demote) a promoted dataset entirely.

        Args:
            promoted_id: Dataset to demote

        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DELETE FROM {}.{} WHERE promoted_id = %s RETURNING promoted_id").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (promoted_id,)
                )
                deleted = cur.fetchone()
                conn.commit()

                if deleted:
                    logger.info(f"Demoted dataset: {promoted_id}")
                return deleted is not None

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_model(self, row: Dict[str, Any]) -> PromotedDataset:
        """Convert database row to PromotedDataset model."""
        return PromotedDataset(
            promoted_id=row['promoted_id'],
            stac_collection_id=row.get('stac_collection_id'),
            stac_item_id=row.get('stac_item_id'),
            title=row.get('title'),
            description=row.get('description'),
            thumbnail_url=row.get('thumbnail_url'),
            thumbnail_generated_at=row.get('thumbnail_generated_at'),
            tags=row.get('tags', []),
            viewer_config=row.get('viewer_config', {}),
            style_id=row.get('style_id'),
            in_gallery=row.get('in_gallery', False),
            gallery_order=row.get('gallery_order'),
            promoted_at=row.get('promoted_at'),
            updated_at=row.get('updated_at')
        )

    def exists(self, promoted_id: str) -> bool:
        """Check if a promoted dataset exists."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT 1 FROM {}.{} WHERE promoted_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (promoted_id,)
                )
                return cur.fetchone() is not None


# Module exports
__all__ = ['PromotedDatasetRepository']
