# ============================================================================
# CLAUDE CONTEXT - RELEASE REPOSITORY (VERSIONED ARTIFACT LIFECYCLE)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Infrastructure - V0.9 AssetRelease entity CRUD
# PURPOSE: Database operations for app.asset_releases table
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: ReleaseRepository
# DEPENDENCIES: psycopg, core.models.asset
# ============================================================================
"""
Release Repository -- Versioned Artifact Lifecycle CRUD.

Part of the V0.9 Asset/Release entity split. Handles all persistence for
app.asset_releases, including version assignment, approval state updates,
STAC caching, and is_latest management.

Table: app.asset_releases
Primary Key: release_id
Foreign Keys: asset_id -> app.assets(asset_id), job_id -> app.jobs(job_id)

Lifecycle:
    - Created as draft (version_id=None, approval_state=PENDING_REVIEW)
    - Approved -> gets version_id ("v1", "v2", ...) and version_ordinal
    - Rejected -> can be overwritten with new data
    - Approved -> can be revoked (requires audit trail)

Methods:
    CREATE:
        create(release) - Insert new release record

    READ:
        get_by_id(release_id) - Lookup by primary key
        get_draft(asset_id) - Get current draft for an asset
        get_by_version(asset_id, version_id) - Get specific version
        get_latest(asset_id) - Get latest approved release
        get_by_job_id(job_id) - Find release by processing job
        get_by_request_id(request_id) - Find release by API request
        list_by_asset(asset_id) - All releases for an asset
        list_by_approval_state(state, limit) - Filter by approval state
        list_pending_review(limit) - Convenience: completed + pending_review

    UPDATE:
        update_approval_state(...) - Approve/reject with audit fields
        update_clearance(...) - Set clearance level (OUO/PUBLIC)
        update_revocation(...) - Revoke with audit trail
        update_processing_status(...) - Processing lifecycle updates
        update_version_assignment(...) - Assign version at approval
        update_overwrite(...) - Reset processing for re-submission
        update_stac_item_json(...) - Cache STAC item for materialization
        update_physical_outputs(...) - Set blob_path, table_name, etc.

    LIFECYCLE:
        flip_is_latest(asset_id, new_latest_release_id) - Atomic is_latest swap
        count_by_approval_state() - Dashboard statistics

Exports:
    ReleaseRepository: CRUD operations for asset releases

Created: 21 FEB 2026 as part of V0.9 Asset/Release entity split
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from psycopg import sql
from psycopg.errors import UniqueViolation

from util_logger import LoggerFactory, ComponentType
from core.models.asset import AssetRelease, ApprovalState, ClearanceState, ProcessingStatus
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "ReleaseRepository")


class ReleaseRepository(PostgreSQLRepository):
    """
    Repository for asset release operations.

    Handles CRUD operations for app.asset_releases table.
    Manages versioned artifact lifecycle including approval,
    clearance, processing, and is_latest tracking.

    Table: app.asset_releases
    """

    # Column list shared by create() and create_and_count_atomic()
    _INSERT_COLUMNS = (
        "release_id", "asset_id",
        "version_id", "suggested_version_id", "version_ordinal",
        "revision", "previous_release_id",
        "is_latest", "is_served", "request_id",
        "blob_path", "stac_item_id", "stac_collection_id",
        "stac_item_json", "content_hash", "source_file_hash", "output_file_hash",
        "output_mode", "tile_count", "search_id",
        "job_id", "processing_status", "processing_started_at",
        "processing_completed_at", "last_error", "workflow_id", "node_summary",
        "approval_state", "reviewer", "reviewed_at", "rejection_reason",
        "approval_notes", "clearance_state", "adf_run_id",
        "cleared_at", "cleared_by", "made_public_at", "made_public_by",
        "revoked_at", "revoked_by", "revocation_reason",
        "created_at", "updated_at", "priority",
    )

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "asset_releases"
        self.schema = "app"

    def _build_insert_values(self, release: AssetRelease, now: datetime) -> tuple:
        """Extract ordered values from release model to match _INSERT_COLUMNS."""
        return (
            release.release_id, release.asset_id,
            release.version_id, release.suggested_version_id,
            release.version_ordinal,
            release.revision, release.previous_release_id,
            release.is_latest, release.is_served, release.request_id,
            release.blob_path,
            release.stac_item_id, release.stac_collection_id,
            release.stac_item_json, release.content_hash,
            release.source_file_hash, release.output_file_hash,
            release.output_mode, release.tile_count, release.search_id,
            release.job_id, release.processing_status,
            release.processing_started_at,
            release.processing_completed_at, release.last_error,
            release.workflow_id, release.node_summary,
            release.approval_state, release.reviewer,
            release.reviewed_at, release.rejection_reason,
            release.approval_notes, release.clearance_state,
            release.adf_run_id,
            release.cleared_at, release.cleared_by,
            release.made_public_at, release.made_public_by,
            release.revoked_at, release.revoked_by,
            release.revocation_reason,
            now, now,
            release.priority,
        )

    def _build_insert_sql(self) -> sql.Composed:
        """Build the INSERT ... RETURNING * SQL for asset_releases."""
        cols = ", ".join(self._INSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(self._INSERT_COLUMNS))
        return sql.SQL(
            f"INSERT INTO {{}}.{{}} ({cols}) VALUES ({placeholders}) RETURNING *"
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.table)
        )

    # =========================================================================
    # CREATE
    # =========================================================================

    def create(self, release: AssetRelease) -> AssetRelease:
        """
        Create a new asset release record.

        Inserts all fields with explicit column enumeration. Psycopg3 type
        adapters handle dict->JSONB, Enum->.value, and datetime serialization
        automatically.

        Args:
            release: AssetRelease model to insert

        Returns:
            Created AssetRelease with database-assigned timestamps

        Raises:
            psycopg.errors.UniqueViolation: If release_id already exists
        """
        logger.info(f"Creating release: {release.release_id} for asset {release.asset_id}")

        now = datetime.now(timezone.utc)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    self._build_insert_sql(),
                    self._build_insert_values(release, now)
                )
                row = cur.fetchone()
                conn.commit()

                logger.info(f"Created release: {release.release_id}")
                return self._row_to_model(row)

    def create_and_count_atomic(self, release: AssetRelease) -> AssetRelease:
        """
        Create a release and increment the parent asset's release_count atomically.

        Bundles INSERT into asset_releases + UPDATE assets.release_count in a
        single connection/transaction. Both succeed or both roll back.

        Follows the same pattern as approve_release_atomic().

        Args:
            release: AssetRelease model to insert

        Returns:
            Created AssetRelease with database-assigned timestamps

        Raises:
            psycopg.errors.UniqueViolation: If release_id already exists
            RuntimeError: If asset not found (release_count update affected 0 rows)
        """
        logger.info(
            f"Atomic create+count: release={release.release_id} "
            f"asset={release.asset_id}"
        )

        now = datetime.now(timezone.utc)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Step 1: INSERT release
                cur.execute(
                    self._build_insert_sql(),
                    self._build_insert_values(release, now)
                )
                row = cur.fetchone()

                # Step 2: Increment asset.release_count
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET release_count = release_count + 1,
                            updated_at = %s
                        WHERE asset_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier("assets")
                    ),
                    (now, release.asset_id)
                )

                if cur.rowcount == 0:
                    conn.rollback()
                    raise RuntimeError(
                        f"Asset {release.asset_id} not found — "
                        f"cannot increment release_count"
                    )

                conn.commit()

                logger.info(
                    f"Atomic create+count complete: release={release.release_id}, "
                    f"asset={release.asset_id}"
                )
                return self._row_to_model(row)

    # =========================================================================
    # READ
    # =========================================================================

    def get_by_id(self, release_id: str) -> Optional[AssetRelease]:
        """
        Get a release by its primary key.

        Args:
            release_id: Release identifier

        Returns:
            AssetRelease if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE release_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_draft(self, asset_id: str) -> Optional[AssetRelease]:
        """
        Get the current draft release for an asset.

        A draft is a release with no version_id assigned and not revoked.
        Returns the newest draft if multiple exist.

        Args:
            asset_id: Parent asset identifier

        Returns:
            AssetRelease draft if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s
                          AND version_id IS NULL
                          AND approval_state != %s
                        ORDER BY created_at DESC
                        LIMIT 1
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, ApprovalState.REVOKED)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_version(self, asset_id: str, version_id: str) -> Optional[AssetRelease]:
        """
        Get a specific version of a release.

        Args:
            asset_id: Parent asset identifier
            version_id: Version identifier (e.g., "v1", "v2")

        Returns:
            AssetRelease if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s AND version_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, version_id)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_suggested_version(self, asset_id: str, suggested_version_id: str) -> Optional[AssetRelease]:
        """
        Get a release by its DDH-provided suggested version ID.

        Used when the external caller's version_id may differ from the
        internal version_id assigned at approval time.

        Args:
            asset_id: Parent asset identifier
            suggested_version_id: DDH-provided version (e.g., "v1.0")

        Returns:
            AssetRelease if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s AND suggested_version_id = %s
                        ORDER BY created_at DESC LIMIT 1
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, suggested_version_id)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_latest(self, asset_id: str) -> Optional[AssetRelease]:
        """
        Get the latest approved release for an asset.

        Uses the is_latest flag + approval_state='approved' filter.

        Args:
            asset_id: Parent asset identifier

        Returns:
            AssetRelease if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s
                          AND is_latest = true
                          AND approval_state = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, ApprovalState.APPROVED)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_job_id(self, job_id: str) -> Optional[AssetRelease]:
        """
        Get a release by its processing job ID.

        Args:
            job_id: Job identifier

        Returns:
            AssetRelease if found, None otherwise
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

    def get_by_request_id(self, request_id: str) -> Optional[AssetRelease]:
        """
        Get a release by its API request ID.

        Args:
            request_id: API request identifier

        Returns:
            AssetRelease if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE request_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (request_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_stac_item_id(self, stac_item_id: str) -> Optional[AssetRelease]:
        """
        Get a release by its STAC item ID.

        Args:
            stac_item_id: STAC item identifier

        Returns:
            AssetRelease if found, None otherwise
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

    def list_by_asset(self, asset_id: str) -> List[AssetRelease]:
        """
        List all releases for an asset, ordered by version.

        Drafts (version_ordinal IS NULL) sort last, then by created_at DESC.

        Args:
            asset_id: Parent asset identifier

        Returns:
            List of AssetRelease models
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s
                        ORDER BY version_ordinal NULLS LAST, created_at DESC
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id,)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def get_next_version_ordinal(self, asset_id: str) -> int:
        """
        Get the next version ordinal for a new release under this asset.

        Returns MAX(version_ordinal) + 1 from ALL releases with assigned ordinals.
        Returns 1 if no releases with ordinals exist (first release).

        Args:
            asset_id: Parent asset identifier

        Returns:
            Next sequential ordinal (1, 2, 3, ...)
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT COALESCE(MAX(version_ordinal), 0) + 1 AS next_ordinal
                        FROM {}.{}
                        WHERE asset_id = %s
                          AND version_ordinal IS NOT NULL
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id,)
                )
                return cur.fetchone()['next_ordinal']

    def list_by_approval_state(
        self,
        state: ApprovalState,
        limit: int = 50
    ) -> List[AssetRelease]:
        """
        List releases by approval state.

        Args:
            state: Approval state to filter by
            limit: Maximum number of results

        Returns:
            List of AssetRelease models ordered by created_at DESC
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE approval_state = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (state, limit)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_pending_review(self, limit: int = 50) -> List[AssetRelease]:
        """
        List releases that are pending review and have completed processing.

        Returns oldest first so reviewers process in submission order.

        Args:
            limit: Maximum number of results

        Returns:
            List of AssetRelease models ordered by created_at ASC
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE approval_state = %s
                          AND processing_status = %s
                        ORDER BY created_at ASC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (ApprovalState.PENDING_REVIEW, ProcessingStatus.COMPLETED, limit)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    # =========================================================================
    # UPDATE (targeted column updates -- NOT full row replace)
    # =========================================================================

    def update_approval_state(
        self,
        release_id: str,
        approval_state: ApprovalState,
        reviewer: str,
        reviewed_at: datetime,
        rejection_reason: str = None,
        approval_notes: str = None
    ) -> bool:
        """
        Update approval state with audit fields.

        Args:
            release_id: Release to update
            approval_state: New approval state
            reviewer: Who made the decision
            reviewed_at: When the decision was made
            rejection_reason: Required if REJECTED
            approval_notes: Optional reviewer notes

        Returns:
            True if updated, False if release not found or already transitioned
        """
        logger.info(f"Updating approval state for {release_id[:16]}... to {approval_state.value}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET approval_state = %s,
                            reviewer = %s,
                            reviewed_at = %s,
                            rejection_reason = %s,
                            approval_notes = %s,
                            updated_at = NOW()
                        WHERE release_id = %s
                          AND approval_state = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        approval_state, reviewer, reviewed_at,
                        rejection_reason, approval_notes,
                        release_id,
                        ApprovalState.PENDING_REVIEW.value
                    )
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Updated approval state for {release_id[:16]}... to {approval_state.value}")
                else:
                    logger.warning(f"No rows updated for {release_id[:16]}... — release not found or not in pending_review state")
                return updated

    def update_clearance(
        self,
        release_id: str,
        clearance_state: ClearanceState,
        cleared_by: str = None,
        adf_run_id: str = None
    ) -> bool:
        """
        Update clearance state with audit fields.

        If clearance_state is PUBLIC, also sets made_public_at and
        made_public_by.

        Args:
            release_id: Release to update
            clearance_state: New clearance level (UNCLEARED, OUO, PUBLIC)
            cleared_by: Who granted clearance
            adf_run_id: ADF pipeline run ID (if PUBLIC)

        Returns:
            True if updated, False if release not found
        """
        logger.info(f"Updating clearance for {release_id[:16]}... to {clearance_state.value}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                if clearance_state == ClearanceState.PUBLIC:
                    # PUBLIC: also set made_public_at and made_public_by
                    cur.execute(
                        sql.SQL("""
                            UPDATE {}.{}
                            SET clearance_state = %s,
                                cleared_at = NOW(),
                                cleared_by = %s,
                                adf_run_id = %s,
                                made_public_at = NOW(),
                                made_public_by = %s,
                                updated_at = NOW()
                            WHERE release_id = %s
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        ),
                        (clearance_state, cleared_by, adf_run_id, cleared_by, release_id)
                    )
                else:
                    # OUO or UNCLEARED: set cleared_at/by but not made_public
                    cur.execute(
                        sql.SQL("""
                            UPDATE {}.{}
                            SET clearance_state = %s,
                                cleared_at = NOW(),
                                cleared_by = %s,
                                adf_run_id = %s,
                                updated_at = NOW()
                            WHERE release_id = %s
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        ),
                        (clearance_state, cleared_by, adf_run_id, release_id)
                    )

                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Updated clearance for {release_id[:16]}... to {clearance_state.value}")
                return updated

    def update_revocation(
        self,
        release_id: str,
        revoked_by: str,
        revocation_reason: str
    ) -> bool:
        """
        Revoke a release with audit trail.

        Sets approval_state to REVOKED and is_latest to false.

        Args:
            release_id: Release to revoke
            revoked_by: Who is revoking
            revocation_reason: Why (required for audit)

        Returns:
            True if updated, False if release not found
        """
        logger.info(f"AUDIT: Revoking release {release_id[:16]}... by {revoked_by}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET approval_state = %s,
                            revoked_at = NOW(),
                            revoked_by = %s,
                            revocation_reason = %s,
                            is_latest = false,
                            updated_at = NOW()
                        WHERE release_id = %s
                          AND approval_state = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (ApprovalState.REVOKED, revoked_by, revocation_reason, release_id, ApprovalState.APPROVED)
                )
                updated = cur.rowcount > 0
                conn.commit()
                if updated:
                    logger.warning(f"AUDIT: Release {release_id[:16]}... REVOKED by {revoked_by}")
                return updated

    def link_job(self, release_id: str, job_id: str) -> bool:
        """
        Link a processing job to a release.

        Sets job_id and resets processing_status to PENDING.

        Args:
            release_id: Release to link
            job_id: Job identifier

        Returns:
            True if updated, False if release not found
        """
        logger.info(f"Linking job {job_id[:16]}... to release {release_id[:16]}...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET job_id = %s,
                            processing_status = %s,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (job_id, ProcessingStatus.PENDING, release_id)
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Linked job {job_id[:16]}... to release {release_id[:16]}...")
                return updated

    def update_processing_status(
        self,
        release_id: str,
        status: ProcessingStatus,
        started_at: datetime = None,
        completed_at: datetime = None,
        error: str = None
    ) -> bool:
        """
        Update processing lifecycle status.

        Uses COALESCE for processing_started_at so it preserves the original
        start time unless explicitly provided.

        Args:
            release_id: Release to update
            status: New processing status
            started_at: When processing started (preserved if None)
            completed_at: When processing completed
            error: Error message if failed

        Returns:
            True if updated, False if release not found
        """
        logger.info(f"Updating processing status for {release_id[:16]}... to {status.value}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET processing_status = %s,
                            processing_started_at = COALESCE(%s, processing_started_at),
                            processing_completed_at = %s,
                            last_error = %s,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (status, started_at, completed_at, error, release_id)
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Updated processing status for {release_id[:16]}... to {status.value}")
                return updated

    def update_version_assignment(
        self,
        release_id: str,
        version_id: str,
        version_ordinal: int,
        is_latest: bool
    ) -> bool:
        """
        Assign version at approval time.

        Called when a draft is approved and assigned a formal version
        (e.g., "v1", "v2") and ordinal.

        Args:
            release_id: Release to update
            version_id: Version identifier (e.g., "v1")
            version_ordinal: Numeric ordering (1, 2, 3...)
            is_latest: Whether this becomes the latest release

        Returns:
            True if updated, False if release not found
        """
        logger.info(f"Assigning version {version_id} (ordinal={version_ordinal}) to {release_id[:16]}...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET version_id = %s,
                            version_ordinal = %s,
                            is_latest = %s,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (version_id, version_ordinal, is_latest, release_id)
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Assigned version {version_id} to release {release_id[:16]}...")
                return updated

    def update_overwrite(self, release_id: str, revision: int) -> bool:
        """
        Reset processing lifecycle for re-submission (overwrite).

        Increments the revision counter and resets all processing fields
        so the release can be re-processed.

        Args:
            release_id: Release to reset
            revision: New revision number

        Returns:
            True if updated, False if release not found
        """
        logger.info(f"Resetting release {release_id[:16]}... for overwrite (revision={revision})")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET revision = %s,
                            processing_status = %s,
                            approval_state = %s,
                            rejection_reason = NULL,
                            reviewer = NULL,
                            reviewed_at = NULL,
                            job_id = NULL,
                            processing_started_at = NULL,
                            processing_completed_at = NULL,
                            last_error = NULL,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (revision, ProcessingStatus.PENDING, ApprovalState.PENDING_REVIEW, release_id)
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Reset release {release_id[:16]}... for overwrite at revision {revision}")
                return updated

    def update_stac_item_json(self, release_id: str, stac_item_json: dict) -> bool:
        """
        Cache STAC item JSON for materialization to pgSTAC.

        Args:
            release_id: Release to update
            stac_item_json: STAC item dict to cache

        Returns:
            True if updated, False if release not found
        """
        logger.info(f"Updating STAC item JSON for {release_id[:16]}...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET stac_item_json = %s,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (stac_item_json, release_id)
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Updated STAC item JSON for {release_id[:16]}...")
                return updated

    def update_physical_outputs(
        self,
        release_id: str,
        blob_path: str = None,
        stac_item_id: str = None,
        content_hash: str = None,
        source_file_hash: str = None,
        output_file_hash: str = None,
        output_mode: str = None,
        tile_count: int = None,
        search_id: str = None
    ) -> bool:
        """
        Update physical output fields (dynamic -- only provided fields).

        Builds the SET clause dynamically from provided arguments.
        Always includes updated_at = NOW().

        Note: table_name removed (26 FEB 2026) — now in app.release_tables.

        Args:
            release_id: Release to update
            blob_path: Azure Blob Storage path for raster outputs
            stac_item_id: STAC item identifier
            content_hash: Hash of processed output content
            source_file_hash: Hash of original source file
            output_file_hash: Hash of final output file
            output_mode: Output format ('single' or 'tiled')
            tile_count: Number of COG tiles (tiled output only)
            search_id: pgSTAC search hash (tiled output only)

        Returns:
            True if updated, False if release not found or no fields provided
        """
        # Build dynamic SET clause from provided fields
        set_parts = []
        values = []

        field_map = {
            'blob_path': blob_path,
            'stac_item_id': stac_item_id,
            'content_hash': content_hash,
            'source_file_hash': source_file_hash,
            'output_file_hash': output_file_hash,
            'output_mode': output_mode,
            'tile_count': tile_count,
            'search_id': search_id,
        }

        for col_name, col_value in field_map.items():
            if col_value is not None:
                set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(col_name)))
                values.append(col_value)

        if not set_parts:
            logger.info(f"No physical output fields to update for {release_id[:16]}...")
            return False

        # Always include updated_at
        set_parts.append(sql.SQL("updated_at = NOW()"))

        # Add release_id for WHERE clause
        values.append(release_id)

        logger.info(f"Updating physical outputs for {release_id[:16]}... ({len(set_parts) - 1} fields)")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("UPDATE {}.{} SET {} WHERE release_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.SQL(", ").join(set_parts)
                    ),
                    values
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Updated physical outputs for {release_id[:16]}...")
                return updated

    def update_last_error(self, release_id: str, last_error: str) -> bool:
        """
        Update last_error field on a release.

        Used to persist error context when post-atomic operations fail
        (e.g., STAC materialization after approval commit).

        Args:
            release_id: Release to update
            last_error: Error message to persist

        Returns:
            True if updated, False if release not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET last_error = %s,
                            updated_at = %s
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (last_error, datetime.now(timezone.utc), release_id)
                )
                conn.commit()
                return cur.rowcount > 0

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def flip_is_latest(self, asset_id: str, new_latest_release_id: str) -> bool:
        """
        Atomically flip is_latest from all releases to a specific one.

        In a single transaction:
        1. Sets is_latest=false for ALL releases of this asset
        2. Sets is_latest=true for the specified release

        Args:
            asset_id: Parent asset identifier
            new_latest_release_id: Release to mark as latest

        Returns:
            True if the target release was updated, False otherwise
        """
        logger.info(f"Flipping is_latest for asset {asset_id[:16]}... to release {new_latest_release_id[:16]}...")

        now = datetime.now(timezone.utc)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Step 1: Clear is_latest for all releases of this asset
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET is_latest = false, updated_at = %s
                        WHERE asset_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (now, asset_id)
                )

                # Step 2: Set is_latest for the specific release
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET is_latest = true, updated_at = %s
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (now, new_latest_release_id)
                )
                target_updated = cur.rowcount > 0

                if target_updated:
                    conn.commit()
                    logger.info(f"Flipped is_latest: asset {asset_id[:16]}... -> release {new_latest_release_id[:16]}...")
                else:
                    # Target release not found -- rollback Step 1 (which
                    # cleared is_latest on ALL sibling releases). Without
                    # rollback, every release for this asset would have
                    # is_latest=false with no latest release.
                    conn.rollback()
                    logger.warning(
                        f"flip_is_latest: target release {new_latest_release_id[:16]}... "
                        f"not found, rolled back is_latest clear for asset {asset_id[:16]}..."
                    )

                return target_updated

    def approve_release_atomic(
        self,
        release_id: str,
        asset_id: str,
        version_id: str,
        version_ordinal: int,
        approval_state: ApprovalState,
        reviewer: str,
        reviewed_at: datetime,
        clearance_state: ClearanceState,
        approval_notes: str = None
    ) -> bool:
        """
        Atomically approve a release: flip is_latest + assign version +
        set approval state + set clearance in a single transaction.

        Spec: version-conflict-guard -- adds NOT EXISTS subquery to prevent
        two releases for the same (asset_id, version_id) from both being
        approved. UniqueViolation from idx_releases_version_conflict is
        caught as a concurrent-race fallback (R2).

        Combines flip_is_latest(), update_version_assignment(),
        update_approval_state(), and update_clearance() into one
        connection/commit to prevent partial state on failure.

        The WHERE guard 'approval_state = pending_review' ensures
        idempotent safety -- concurrent approvals fail cleanly (0 rows).
        The NOT EXISTS guard prevents version_id collisions across releases.

        Args:
            release_id: Release to approve
            asset_id: Parent asset (for flip_is_latest across siblings)
            version_id: Version to assign (e.g., "v1")
            version_ordinal: Numeric ordering (1, 2, 3...)
            approval_state: Must be APPROVED
            reviewer: Who approved
            reviewed_at: When approved
            clearance_state: OUO or PUBLIC
            approval_notes: Optional reviewer notes

        Returns:
            True if approved, False if release not found, not in
            pending_review state, or version conflict (concurrent approval)
        """
        logger.info(
            f"Atomic approve: release {release_id[:16]}... "
            f"version={version_id}, ordinal={version_ordinal}, "
            f"clearance={clearance_state.value}, reviewer={reviewer}"
        )

        is_public = (clearance_state == ClearanceState.PUBLIC)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    # Step 1: Clear is_latest for all releases of this asset
                    cur.execute(
                        sql.SQL("""
                            UPDATE {}.{}
                            SET is_latest = false, updated_at = %s
                            WHERE asset_id = %s AND is_latest = true
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        ),
                        (reviewed_at, asset_id)
                    )

                    # Step 2: Approve + version + is_latest + clearance in one UPDATE
                    # NOT EXISTS prevents approving when another release already
                    # holds the same (asset_id, version_id) in approved state.
                    if is_public:
                        cur.execute(
                            sql.SQL("""
                                UPDATE {}.{}
                                SET version_id = %s,
                                    version_ordinal = %s,
                                    is_latest = true,
                                    approval_state = %s,
                                    reviewer = %s,
                                    reviewed_at = %s,
                                    approval_notes = %s,
                                    rejection_reason = NULL,
                                    clearance_state = %s,
                                    cleared_at = %s,
                                    cleared_by = %s,
                                    made_public_at = %s,
                                    made_public_by = %s,
                                    updated_at = %s
                                WHERE release_id = %s
                                  AND approval_state = %s
                                  AND NOT EXISTS (
                                      SELECT 1 FROM {}.{}
                                      WHERE asset_id = %s
                                        AND version_id = %s
                                        AND approval_state = %s
                                        AND release_id != %s
                                  )
                            """).format(
                                sql.Identifier(self.schema),
                                sql.Identifier(self.table),
                                sql.Identifier(self.schema),
                                sql.Identifier(self.table)
                            ),
                            (
                                version_id, version_ordinal,
                                approval_state, reviewer, reviewed_at,
                                approval_notes,
                                clearance_state, reviewed_at, reviewer,
                                reviewed_at, reviewer,
                                reviewed_at,
                                release_id,
                                ApprovalState.PENDING_REVIEW,
                                asset_id, version_id,
                                ApprovalState.APPROVED, release_id
                            )
                        )
                    else:
                        cur.execute(
                            sql.SQL("""
                                UPDATE {}.{}
                                SET version_id = %s,
                                    version_ordinal = %s,
                                    is_latest = true,
                                    approval_state = %s,
                                    reviewer = %s,
                                    reviewed_at = %s,
                                    approval_notes = %s,
                                    rejection_reason = NULL,
                                    clearance_state = %s,
                                    cleared_at = %s,
                                    cleared_by = %s,
                                    updated_at = %s
                                WHERE release_id = %s
                                  AND approval_state = %s
                                  AND NOT EXISTS (
                                      SELECT 1 FROM {}.{}
                                      WHERE asset_id = %s
                                        AND version_id = %s
                                        AND approval_state = %s
                                        AND release_id != %s
                                  )
                            """).format(
                                sql.Identifier(self.schema),
                                sql.Identifier(self.table),
                                sql.Identifier(self.schema),
                                sql.Identifier(self.table)
                            ),
                            (
                                version_id, version_ordinal,
                                approval_state, reviewer, reviewed_at,
                                approval_notes,
                                clearance_state, reviewed_at, reviewer,
                                reviewed_at,
                                release_id,
                                ApprovalState.PENDING_REVIEW,
                                asset_id, version_id,
                                ApprovalState.APPROVED, release_id
                            )
                        )

                    approved = cur.rowcount > 0

                    if approved:
                        conn.commit()
                        logger.info(
                            f"Atomic approve committed: {release_id[:16]}... "
                            f"-> {version_id} (ordinal={version_ordinal})"
                        )
                    else:
                        conn.rollback()
                        logger.warning(
                            f"Atomic approve failed: {release_id[:16]}... "
                            f"not found, not in pending_review state, or version conflict"
                        )

                    return approved

                except UniqueViolation:
                    # R2: READ COMMITTED race -- another transaction committed the
                    # same (asset_id, version_id) between our NOT EXISTS check and
                    # our UPDATE. The partial unique index catches this at commit.
                    # Explicit rollback undoes Step 1's is_latest clear.
                    conn.rollback()
                    logger.warning(
                        f"UniqueViolation on approve: {release_id[:16]}... "
                        f"version_id={version_id} already approved for asset "
                        f"(concurrent race)"
                    )
                    return False

    def rollback_approval_atomic(
        self,
        release_id: str,
        asset_id: str,
        reason: str = "STAC materialization failed"
    ) -> bool:
        """
        Roll back a committed approval when post-atomic operations fail.

        Spec: version-conflict-guard -- reverts approval_state to PENDING_REVIEW,
        clears version_id/is_latest/clearance_state, and promotes the next
        most recent approved sibling to is_latest if one exists.

        Preserves: reviewer, reviewed_at, approval_notes, stac_item_id,
        stac_collection_id, blob_path (for audit trail and retry).
        Clears: version_id, is_latest, clearance_state.

        Args:
            release_id: The release whose approval is being rolled back
            asset_id: Parent asset (for sibling is_latest promotion)
            reason: Why the rollback occurred (stored in last_error)

        Returns:
            True if rollback succeeded, False if release was not in
            approved state (already rolled back or concurrently modified)
        """
        logger.warning(
            f"Rolling back approval: {release_id[:16]}... reason={reason}"
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Step 1: Revert the target release
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET approval_state = %s,
                            version_id = NULL,
                            is_latest = false,
                            clearance_state = %s,
                            last_error = %s,
                            updated_at = %s
                        WHERE release_id = %s
                          AND approval_state = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        ApprovalState.PENDING_REVIEW,
                        ClearanceState.UNCLEARED,
                        f"ROLLBACK: {reason}",
                        datetime.now(timezone.utc),
                        release_id,
                        ApprovalState.APPROVED
                    )
                )

                reverted = cur.rowcount > 0

                if reverted:
                    # Step 2: Promote next most recent approved sibling to is_latest
                    cur.execute(
                        sql.SQL("""
                            UPDATE {}.{}
                            SET is_latest = true,
                                updated_at = %s
                            WHERE release_id = (
                                SELECT release_id FROM {}.{}
                                WHERE asset_id = %s
                                  AND approval_state = %s
                                  AND release_id != %s
                                ORDER BY version_ordinal DESC, reviewed_at DESC
                                LIMIT 1
                            )
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table),
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        ),
                        (
                            datetime.now(timezone.utc),
                            asset_id,
                            ApprovalState.APPROVED,
                            release_id
                        )
                    )
                    conn.commit()
                    logger.warning(
                        f"Approval rollback committed: {release_id[:16]}... "
                        f"reason={reason}"
                    )
                else:
                    conn.rollback()
                    logger.warning(
                        f"Approval rollback no-op: {release_id[:16]}... "
                        f"not in approved state (concurrent modification?)"
                    )

                return reverted

    def get_approved_by_version(self, asset_id: str, version_id: str) -> Optional[AssetRelease]:
        """
        Get an approved release for a specific (asset_id, version_id) pair.

        Spec: version-conflict-guard -- used to probe for the conflicting
        release when approve_release_atomic() returns False, so the service
        layer can distinguish VersionConflict from generic ApprovalFailed.

        Args:
            asset_id: Parent asset identifier
            version_id: Version identifier (e.g., "v1", "v2")

        Returns:
            AssetRelease if an approved release with that version exists,
            None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s
                          AND version_id = %s
                          AND approval_state = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, version_id, ApprovalState.APPROVED)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def count_by_approval_state(self) -> Dict[str, int]:
        """
        Get counts of releases grouped by approval_state.

        Returns:
            Dict like {'pending_review': 5, 'approved': 100, 'rejected': 2, 'revoked': 1}
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT approval_state, COUNT(*) as count
                        FROM {}.{}
                        GROUP BY approval_state
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    )
                )
                rows = cur.fetchall()

                # Initialize all states with 0
                counts = {state.value: 0 for state in ApprovalState}

                # Update with actual counts
                for row in rows:
                    if row['approval_state'] in counts:
                        counts[row['approval_state']] = row['count']

                return counts

    # =========================================================================
    # INTERNAL
    # =========================================================================

    def _row_to_model(self, row: Dict[str, Any]) -> AssetRelease:
        """
        Convert database row to AssetRelease model.

        Parses enum fields from string values — raises ValueError on invalid
        or missing values (no silent fallbacks per project convention).
        JSONB columns (stac_item_json, node_summary, platform_refs) are
        passed directly from the row -- psycopg3 returns them as dicts.

        Args:
            row: Database row as dict (from dict_row cursor)

        Returns:
            AssetRelease model instance
        """
        # Parse enums — fail explicitly on invalid values (no silent fallbacks)
        approval_state_value = row.get('approval_state')
        if not approval_state_value:
            raise ValueError(f"Missing approval_state for release {row.get('release_id', '?')}")
        approval_state = ApprovalState(approval_state_value)

        clearance_state_value = row.get('clearance_state')
        if not clearance_state_value:
            raise ValueError(f"Missing clearance_state for release {row.get('release_id', '?')}")
        clearance_state = ClearanceState(clearance_state_value)

        processing_status_value = row.get('processing_status')
        if not processing_status_value:
            raise ValueError(f"Missing processing_status for release {row.get('release_id', '?')}")
        processing_status = ProcessingStatus(processing_status_value)

        return AssetRelease(
            # Identity
            release_id=row['release_id'],
            asset_id=row['asset_id'],
            # Version
            version_id=row.get('version_id'),
            suggested_version_id=row.get('suggested_version_id'),
            version_ordinal=row.get('version_ordinal') or 0,
            revision=row.get('revision', 1),
            previous_release_id=row.get('previous_release_id'),
            # Flags
            is_latest=row.get('is_latest', False),
            is_served=row.get('is_served', True),
            request_id=row.get('request_id'),
            # Physical outputs (table_name removed → app.release_tables)
            blob_path=row.get('blob_path'),
            stac_item_id=row.get('stac_item_id', ''),
            stac_collection_id=row.get('stac_collection_id', ''),
            stac_item_json=row.get('stac_item_json'),
            content_hash=row.get('content_hash'),
            source_file_hash=row.get('source_file_hash'),
            output_file_hash=row.get('output_file_hash'),
            # Tiled output metadata
            output_mode=row.get('output_mode'),
            tile_count=row.get('tile_count'),
            search_id=row.get('search_id'),
            # Processing lifecycle
            job_id=row.get('job_id'),
            processing_status=processing_status,
            processing_started_at=row.get('processing_started_at'),
            processing_completed_at=row.get('processing_completed_at'),
            last_error=row.get('last_error'),
            workflow_id=row.get('workflow_id'),
            node_summary=row.get('node_summary'),
            # Approval lifecycle
            approval_state=approval_state,
            reviewer=row.get('reviewer'),
            reviewed_at=row.get('reviewed_at'),
            rejection_reason=row.get('rejection_reason'),
            approval_notes=row.get('approval_notes'),
            clearance_state=clearance_state,
            adf_run_id=row.get('adf_run_id'),
            cleared_at=row.get('cleared_at'),
            cleared_by=row.get('cleared_by'),
            made_public_at=row.get('made_public_at'),
            made_public_by=row.get('made_public_by'),
            # Revocation audit
            revoked_at=row.get('revoked_at'),
            revoked_by=row.get('revoked_by'),
            revocation_reason=row.get('revocation_reason'),
            # Timestamps
            created_at=row.get('created_at', datetime.now(timezone.utc)),
            updated_at=row.get('updated_at', datetime.now(timezone.utc)),
            # Priority
            priority=row.get('priority', 5),
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['ReleaseRepository']
