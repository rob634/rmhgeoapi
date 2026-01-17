# ============================================================================
# DATASET APPROVAL REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Dataset approvals CRUD operations
# PURPOSE: Database operations for app.dataset_approvals table
# LAST_REVIEWED: 16 JAN 2026
# EXPORTS: ApprovalRepository
# DEPENDENCIES: psycopg, core.models.approval
# ============================================================================
"""
Dataset Approval Repository.

Database operations for the dataset approval system. Handles all persistence
for the dataset_approvals table (QA workflow for STAC publication).

Exports:
    ApprovalRepository: CRUD operations for dataset approvals

Created: 16 JAN 2026
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import hashlib

from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from core.models import DatasetApproval, ApprovalStatus
from core.models.promoted import Classification
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "ApprovalRepository")


def generate_approval_id(job_id: str) -> str:
    """
    Generate a unique approval ID from job ID.

    Format: apr-{first 8 chars of SHA256 hash}

    Args:
        job_id: The job ID to generate approval ID from

    Returns:
        Unique approval ID like "apr-a1b2c3d4"
    """
    hash_input = f"approval:{job_id}"
    hash_value = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
    return f"apr-{hash_value}"


class ApprovalRepository(PostgreSQLRepository):
    """
    Repository for dataset approval operations.

    Handles CRUD operations for app.dataset_approvals table.
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "dataset_approvals"
        self.schema = "app"

    # =========================================================================
    # CREATE
    # =========================================================================

    def create(self, approval: DatasetApproval) -> DatasetApproval:
        """
        Create a new dataset approval record.

        Args:
            approval: DatasetApproval model to insert

        Returns:
            Created DatasetApproval with timestamps

        Raises:
            ValueError: If approval_id already exists
        """
        logger.info(f"Creating approval: {approval.approval_id} for job {approval.job_id}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if already exists
                cur.execute(
                    sql.SQL("SELECT 1 FROM {}.{} WHERE approval_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (approval.approval_id,)
                )
                if cur.fetchone():
                    raise ValueError(f"Approval '{approval.approval_id}' already exists")

                # Check if job already has an approval
                cur.execute(
                    sql.SQL("SELECT approval_id FROM {}.{} WHERE job_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (approval.job_id,)
                )
                existing = cur.fetchone()
                if existing:
                    logger.warning(f"Job {approval.job_id} already has approval {existing['approval_id']}")
                    # Return existing approval instead of creating duplicate
                    return self.get_by_id(existing['approval_id'])

                # Insert
                now = datetime.now(timezone.utc)
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            approval_id,
                            job_id, job_type,
                            classification, status,
                            stac_item_id, stac_collection_id,
                            reviewer, notes, rejection_reason,
                            revoked_at, revoked_by, revocation_reason,
                            adf_run_id,
                            created_at, reviewed_at, updated_at
                        ) VALUES (
                            %s,
                            %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s,
                            %s, %s, %s
                        )
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        approval.approval_id,
                        approval.job_id, approval.job_type,
                        approval.classification.value if approval.classification else Classification.OUO.value,
                        approval.status.value if approval.status else ApprovalStatus.PENDING.value,
                        approval.stac_item_id, approval.stac_collection_id,
                        approval.reviewer, approval.notes, approval.rejection_reason,
                        approval.revoked_at, approval.revoked_by, approval.revocation_reason,
                        approval.adf_run_id,
                        now, approval.reviewed_at, now
                    )
                )
                row = cur.fetchone()
                conn.commit()

                logger.info(f"Created approval: {approval.approval_id}")
                return self._row_to_model(row)

    def create_for_job(
        self,
        job_id: str,
        job_type: str,
        classification: Classification = Classification.OUO,
        stac_item_id: Optional[str] = None,
        stac_collection_id: Optional[str] = None
    ) -> DatasetApproval:
        """
        Create a pending approval for a completed job.

        Convenience method that generates approval_id automatically.

        Args:
            job_id: The completed job ID
            job_type: Type of job (process_vector, etc.)
            classification: Data classification (OUO or PUBLIC)
            stac_item_id: STAC item ID if available
            stac_collection_id: STAC collection ID if available

        Returns:
            Created DatasetApproval in PENDING status
        """
        approval = DatasetApproval(
            approval_id=generate_approval_id(job_id),
            job_id=job_id,
            job_type=job_type,
            classification=classification,
            status=ApprovalStatus.PENDING,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id
        )
        return self.create(approval)

    # =========================================================================
    # READ
    # =========================================================================

    def get_by_id(self, approval_id: str) -> Optional[DatasetApproval]:
        """
        Get an approval by ID.

        Args:
            approval_id: Approval identifier

        Returns:
            DatasetApproval if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE approval_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (approval_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_job_id(self, job_id: str) -> Optional[DatasetApproval]:
        """
        Get an approval by job ID.

        Args:
            job_id: Job identifier

        Returns:
            DatasetApproval if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE job_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (job_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_stac_item_id(self, stac_item_id: str) -> Optional[DatasetApproval]:
        """
        Get an approval by STAC item ID.

        This is used by unpublish handlers to check if an item was approved
        and needs revocation before unpublishing.

        Args:
            stac_item_id: STAC item identifier

        Returns:
            DatasetApproval if found, None otherwise
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

    def list_by_status(
        self,
        status: ApprovalStatus,
        limit: int = 50,
        offset: int = 0
    ) -> List[DatasetApproval]:
        """
        List approvals by status.

        Args:
            status: Approval status to filter by
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of DatasetApproval models
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE status = %s
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (status.value, limit, offset)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_pending(self, limit: int = 50) -> List[DatasetApproval]:
        """
        List pending approvals (convenience method).

        Args:
            limit: Maximum number of results

        Returns:
            List of pending DatasetApproval models
        """
        return self.list_by_status(ApprovalStatus.PENDING, limit=limit)

    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[ApprovalStatus] = None,
        classification: Optional[Classification] = None
    ) -> List[DatasetApproval]:
        """
        List all approvals with optional filters.

        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            status: Optional status filter
            classification: Optional classification filter

        Returns:
            List of DatasetApproval models
        """
        conditions = []
        params = []

        if status:
            conditions.append("status = %s")
            params.append(status.value)

        if classification:
            conditions.append("classification = %s")
            params.append(classification.value)

        where_clause = sql.SQL(" AND ").join(
            sql.SQL(c) for c in conditions
        ) if conditions else sql.SQL("TRUE")

        params.extend([limit, offset])

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE {}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        where_clause
                    ),
                    params
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def count_by_status(self) -> Dict[str, int]:
        """
        Count approvals by status.

        Returns:
            Dictionary with status counts
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT status, COUNT(*) as count
                        FROM {}.{}
                        GROUP BY status
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    )
                )
                rows = cur.fetchall()
                return {row['status']: row['count'] for row in rows}

    # =========================================================================
    # UPDATE
    # =========================================================================

    def update(self, approval_id: str, updates: Dict[str, Any]) -> Optional[DatasetApproval]:
        """
        Update an approval record.

        Args:
            approval_id: Approval to update
            updates: Dictionary of field updates

        Returns:
            Updated DatasetApproval if found, None otherwise
        """
        if not updates:
            return self.get_by_id(approval_id)

        # Always update updated_at
        updates['updated_at'] = datetime.now(timezone.utc)

        # Convert enums to values
        if 'status' in updates and isinstance(updates['status'], ApprovalStatus):
            updates['status'] = updates['status'].value
        if 'classification' in updates and isinstance(updates['classification'], Classification):
            updates['classification'] = updates['classification'].value

        # Build SET clause
        set_parts = []
        values = []
        for key, value in updates.items():
            set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            values.append(value)

        values.append(approval_id)  # For WHERE clause

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("UPDATE {}.{} SET {} WHERE approval_id = %s RETURNING *").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.SQL(", ").join(set_parts)
                    ),
                    values
                )
                row = cur.fetchone()
                conn.commit()

                return self._row_to_model(row) if row else None

    def approve(
        self,
        approval_id: str,
        reviewer: str,
        notes: Optional[str] = None,
        adf_run_id: Optional[str] = None
    ) -> Optional[DatasetApproval]:
        """
        Approve a dataset.

        Args:
            approval_id: Approval to approve
            reviewer: Email or identifier of reviewer
            notes: Optional review notes
            adf_run_id: ADF pipeline run ID (if PUBLIC classification triggered ADF)

        Returns:
            Updated DatasetApproval if found, None otherwise

        Raises:
            ValueError: If approval is not in PENDING status
        """
        existing = self.get_by_id(approval_id)
        if not existing:
            return None

        if existing.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Cannot approve: approval {approval_id} is in '{existing.status.value}' status, not 'pending'"
            )

        updates = {
            'status': ApprovalStatus.APPROVED,
            'reviewer': reviewer,
            'reviewed_at': datetime.now(timezone.utc)
        }
        if notes:
            updates['notes'] = notes
        if adf_run_id:
            updates['adf_run_id'] = adf_run_id

        result = self.update(approval_id, updates)
        if result:
            logger.info(f"Approved: {approval_id} by {reviewer}")
        return result

    def reject(
        self,
        approval_id: str,
        reviewer: str,
        reason: str
    ) -> Optional[DatasetApproval]:
        """
        Reject a dataset.

        Args:
            approval_id: Approval to reject
            reviewer: Email or identifier of reviewer
            reason: Rejection reason (required)

        Returns:
            Updated DatasetApproval if found, None otherwise

        Raises:
            ValueError: If approval is not in PENDING status or reason not provided
        """
        if not reason or not reason.strip():
            raise ValueError("Rejection reason is required")

        existing = self.get_by_id(approval_id)
        if not existing:
            return None

        if existing.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Cannot reject: approval {approval_id} is in '{existing.status.value}' status, not 'pending'"
            )

        updates = {
            'status': ApprovalStatus.REJECTED,
            'reviewer': reviewer,
            'rejection_reason': reason,
            'reviewed_at': datetime.now(timezone.utc)
        }

        result = self.update(approval_id, updates)
        if result:
            logger.info(f"Rejected: {approval_id} by {reviewer} - {reason}")
        return result

    def resubmit(self, approval_id: str) -> Optional[DatasetApproval]:
        """
        Resubmit a rejected approval back to pending status.

        Args:
            approval_id: Approval to resubmit

        Returns:
            Updated DatasetApproval if found, None otherwise

        Raises:
            ValueError: If approval is not in REJECTED status
        """
        existing = self.get_by_id(approval_id)
        if not existing:
            return None

        if existing.status != ApprovalStatus.REJECTED:
            raise ValueError(
                f"Cannot resubmit: approval {approval_id} is in '{existing.status.value}' status, not 'rejected'"
            )

        updates = {
            'status': ApprovalStatus.PENDING,
            'reviewer': None,
            'reviewed_at': None,
            'rejection_reason': None
        }

        result = self.update(approval_id, updates)
        if result:
            logger.info(f"Resubmitted: {approval_id} back to pending")
        return result

    def revoke(
        self,
        approval_id: str,
        revoker: str,
        reason: str
    ) -> Optional[DatasetApproval]:
        """
        Revoke an APPROVED approval (for unpublishing).

        This is an undesirable but necessary workflow - marks previously
        approved data as revoked with full audit trail.

        Args:
            approval_id: Approval to revoke
            revoker: Who is revoking (user email or job ID)
            reason: Reason for revocation (required - audit trail)

        Returns:
            Updated DatasetApproval if found, None otherwise

        Raises:
            ValueError: If approval is not in APPROVED status or reason not provided
        """
        if not reason or not reason.strip():
            raise ValueError("Revocation reason is required for audit trail")

        existing = self.get_by_id(approval_id)
        if not existing:
            return None

        if existing.status != ApprovalStatus.APPROVED:
            raise ValueError(
                f"Cannot revoke: approval {approval_id} is in '{existing.status.value}' status, not 'approved'"
            )

        now = datetime.now(timezone.utc)
        updates = {
            'status': ApprovalStatus.REVOKED,
            'revoked_by': revoker,
            'revoked_at': now,
            'revocation_reason': reason
        }

        result = self.update(approval_id, updates)
        if result:
            logger.warning(f"REVOKED: {approval_id} by {revoker} - {reason}")
        return result

    # =========================================================================
    # DELETE
    # =========================================================================

    def delete(self, approval_id: str) -> bool:
        """
        Delete an approval record.

        Args:
            approval_id: Approval to delete

        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DELETE FROM {}.{} WHERE approval_id = %s RETURNING approval_id").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (approval_id,)
                )
                deleted = cur.fetchone()
                conn.commit()

                if deleted:
                    logger.info(f"Deleted approval: {approval_id}")
                return deleted is not None

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_model(self, row: Dict[str, Any]) -> DatasetApproval:
        """Convert database row to DatasetApproval model."""
        # Parse classification
        classification_value = row.get('classification', 'ouo')
        try:
            classification = Classification(classification_value) if classification_value else Classification.OUO
        except ValueError:
            classification = Classification.OUO

        # Parse status
        status_value = row.get('status', 'pending')
        try:
            status = ApprovalStatus(status_value) if status_value else ApprovalStatus.PENDING
        except ValueError:
            status = ApprovalStatus.PENDING

        return DatasetApproval(
            approval_id=row['approval_id'],
            job_id=row['job_id'],
            job_type=row['job_type'],
            classification=classification,
            status=status,
            stac_item_id=row.get('stac_item_id'),
            stac_collection_id=row.get('stac_collection_id'),
            reviewer=row.get('reviewer'),
            notes=row.get('notes'),
            rejection_reason=row.get('rejection_reason'),
            # Revocation tracking (16 JAN 2026)
            revoked_at=row.get('revoked_at'),
            revoked_by=row.get('revoked_by'),
            revocation_reason=row.get('revocation_reason'),
            adf_run_id=row.get('adf_run_id'),
            created_at=row.get('created_at'),
            reviewed_at=row.get('reviewed_at'),
            updated_at=row.get('updated_at')
        )

    def exists(self, approval_id: str) -> bool:
        """Check if an approval exists."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT 1 FROM {}.{} WHERE approval_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (approval_id,)
                )
                return cur.fetchone() is not None


# Module exports
__all__ = ['ApprovalRepository', 'generate_approval_id']
