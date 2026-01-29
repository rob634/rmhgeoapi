# ============================================================================
# ASSET REVISION REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - AssetRevision CRUD operations
# PURPOSE: Database operations for app.asset_revisions table
# LAST_REVIEWED: 29 JAN 2026
# EXPORTS: AssetRevisionRepository
# DEPENDENCIES: psycopg, core.models.asset
# ============================================================================
"""
Asset Revision Repository.

Database operations for the asset revision audit log. Handles all
persistence for the asset_revisions table (V0.8 Entity Architecture).

The revision table is append-only - records the state of an asset
at the moment it was superseded by a new revision.

Exports:
    AssetRevisionRepository: CRUD operations for asset revisions

Created: 29 JAN 2026 as part of V0.8 Entity Architecture
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from uuid import UUID, uuid4

from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from core.models.asset import (
    AssetRevision,
    ApprovalState,
    ClearanceState
)
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "RevisionRepository")


class AssetRevisionRepository(PostgreSQLRepository):
    """
    Repository for asset revision audit operations.

    Handles read operations for app.asset_revisions table.
    This is primarily an append-only audit log.

    Table: app.asset_revisions
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "asset_revisions"
        self.schema = "app"

    # =========================================================================
    # CREATE
    # =========================================================================

    def create(self, revision: AssetRevision) -> AssetRevision:
        """
        Create a new asset revision record.

        Called when an asset is superseded by overwrite.

        Args:
            revision: AssetRevision model to insert

        Returns:
            Created AssetRevision
        """
        logger.info(f"Recording revision {revision.revision} for asset {revision.asset_id}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            revision_id, asset_id, revision,
                            job_id, content_hash,
                            approval_state_at_supersession, clearance_state_at_supersession,
                            reviewer_at_supersession,
                            created_at, superseded_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        str(revision.revision_id),
                        revision.asset_id,
                        revision.revision,
                        revision.job_id,
                        revision.content_hash,
                        revision.approval_state_at_supersession.value if isinstance(revision.approval_state_at_supersession, ApprovalState) else revision.approval_state_at_supersession,
                        revision.clearance_state_at_supersession.value if isinstance(revision.clearance_state_at_supersession, ClearanceState) else revision.clearance_state_at_supersession,
                        revision.reviewer_at_supersession,
                        revision.created_at,
                        revision.superseded_at or datetime.now(timezone.utc)
                    )
                )
                row = cur.fetchone()
                conn.commit()

                logger.info(f"Recorded revision {revision.revision} for asset {revision.asset_id}")
                return self._row_to_model(row)

    def create_from_asset(
        self,
        asset_id: str,
        revision: int,
        job_id: str,
        content_hash: Optional[str],
        approval_state: ApprovalState,
        clearance_state: ClearanceState,
        reviewer: Optional[str],
        original_created_at: datetime
    ) -> AssetRevision:
        """
        Create a revision record from asset snapshot.

        Convenience method that creates an AssetRevision from
        the current state of an asset being superseded.

        Args:
            asset_id: Asset being superseded
            revision: Revision number being superseded
            job_id: Job that created this revision
            content_hash: Content hash at this revision
            approval_state: Approval state at supersession
            clearance_state: Clearance state at supersession
            reviewer: Reviewer at time of supersession
            original_created_at: When this revision was originally created

        Returns:
            Created AssetRevision
        """
        revision_record = AssetRevision(
            revision_id=uuid4(),
            asset_id=asset_id,
            revision=revision,
            job_id=job_id,
            content_hash=content_hash,
            approval_state_at_supersession=approval_state,
            clearance_state_at_supersession=clearance_state,
            reviewer_at_supersession=reviewer,
            created_at=original_created_at,
            superseded_at=datetime.now(timezone.utc)
        )
        return self.create(revision_record)

    # =========================================================================
    # READ
    # =========================================================================

    def get_by_id(self, revision_id: UUID) -> Optional[AssetRevision]:
        """
        Get a revision by ID.

        Args:
            revision_id: Revision record identifier

        Returns:
            AssetRevision if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE revision_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (str(revision_id),)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_asset_and_revision(
        self,
        asset_id: str,
        revision: int
    ) -> Optional[AssetRevision]:
        """
        Get a specific revision for an asset.

        Args:
            asset_id: Asset identifier
            revision: Revision number

        Returns:
            AssetRevision if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s AND revision = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, revision)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def list_by_asset(
        self,
        asset_id: str,
        limit: int = 50
    ) -> List[AssetRevision]:
        """
        List all revisions for an asset.

        Args:
            asset_id: Asset identifier
            limit: Maximum number of results

        Returns:
            List of AssetRevision models ordered by revision descending
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s
                        ORDER BY revision DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, limit)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_by_job(self, job_id: str) -> List[AssetRevision]:
        """
        List all revisions created by a job.

        Args:
            job_id: Job identifier

        Returns:
            List of AssetRevision models
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE job_id = %s
                        ORDER BY superseded_at DESC
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (job_id,)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def count_revisions(self, asset_id: str) -> int:
        """
        Count total revisions for an asset.

        Args:
            asset_id: Asset identifier

        Returns:
            Number of revision records
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT COUNT(*) as count
                        FROM {}.{}
                        WHERE asset_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id,)
                )
                row = cur.fetchone()
                return row['count'] if row else 0

    def get_latest_superseded(
        self,
        asset_id: str
    ) -> Optional[AssetRevision]:
        """
        Get the most recently superseded revision for an asset.

        Args:
            asset_id: Asset identifier

        Returns:
            Most recent AssetRevision if any, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s
                        ORDER BY revision DESC
                        LIMIT 1
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_model(self, row: Dict[str, Any]) -> AssetRevision:
        """Convert database row to AssetRevision model."""
        # Parse revision_id
        revision_id = row['revision_id']
        if isinstance(revision_id, str):
            revision_id = UUID(revision_id)

        # Parse approval_state_at_supersession
        approval_state_value = row.get('approval_state_at_supersession', 'pending_review')
        try:
            approval_state = ApprovalState(approval_state_value) if approval_state_value else ApprovalState.PENDING_REVIEW
        except ValueError:
            approval_state = ApprovalState.PENDING_REVIEW

        # Parse clearance_state_at_supersession
        clearance_state_value = row.get('clearance_state_at_supersession', 'uncleared')
        try:
            clearance_state = ClearanceState(clearance_state_value) if clearance_state_value else ClearanceState.UNCLEARED
        except ValueError:
            clearance_state = ClearanceState.UNCLEARED

        return AssetRevision(
            revision_id=revision_id,
            asset_id=row['asset_id'],
            revision=row['revision'],
            job_id=row['job_id'],
            content_hash=row.get('content_hash'),
            approval_state_at_supersession=approval_state,
            clearance_state_at_supersession=clearance_state,
            reviewer_at_supersession=row.get('reviewer_at_supersession'),
            created_at=row['created_at'],
            superseded_at=row['superseded_at']
        )


# Module exports
__all__ = ['AssetRevisionRepository']
