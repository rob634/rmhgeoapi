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

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "asset_releases"
        self.schema = "app"

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
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            release_id, asset_id,
                            version_id, suggested_version_id, version_ordinal,
                            revision, previous_release_id,
                            is_latest, is_served, request_id,
                            blob_path, table_name, stac_item_id, stac_collection_id,
                            stac_item_json, content_hash, source_file_hash, output_file_hash,
                            job_id, processing_status, processing_started_at,
                            processing_completed_at, last_error, workflow_id, node_summary,
                            approval_state, reviewer, reviewed_at, rejection_reason,
                            approval_notes, clearance_state, adf_run_id,
                            cleared_at, cleared_by, made_public_at, made_public_by,
                            revoked_at, revoked_by, revocation_reason,
                            created_at, updated_at, priority
                        ) VALUES (
                            %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s
                        )
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        # Identity
                        release.release_id, release.asset_id,
                        # Version
                        release.version_id, release.suggested_version_id,
                        release.version_ordinal,
                        release.revision, release.previous_release_id,
                        # Flags
                        release.is_latest, release.is_served, release.request_id,
                        # Physical outputs
                        release.blob_path, release.table_name,
                        release.stac_item_id, release.stac_collection_id,
                        release.stac_item_json, release.content_hash,
                        release.source_file_hash, release.output_file_hash,
                        # Processing lifecycle
                        release.job_id, release.processing_status,
                        release.processing_started_at,
                        release.processing_completed_at, release.last_error,
                        release.workflow_id, release.node_summary,
                        # Approval lifecycle
                        release.approval_state, release.reviewer,
                        release.reviewed_at, release.rejection_reason,
                        release.approval_notes, release.clearance_state,
                        release.adf_run_id,
                        release.cleared_at, release.cleared_by,
                        release.made_public_at, release.made_public_by,
                        # Revocation audit
                        release.revoked_at, release.revoked_by,
                        release.revocation_reason,
                        # Timestamps
                        now, now,
                        # Priority
                        release.priority,
                    )
                )
                row = cur.fetchone()
                conn.commit()

                logger.info(f"Created release: {release.release_id}")
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
            True if updated, False if release not found
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
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        approval_state, reviewer, reviewed_at,
                        rejection_reason, approval_notes,
                        release_id
                    )
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Updated approval state for {release_id[:16]}... to {approval_state.value}")
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
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (ApprovalState.REVOKED, revoked_by, revocation_reason, release_id)
                )
                conn.commit()

                updated = cur.rowcount > 0
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
                            processing_started_at = NULL,
                            processing_completed_at = NULL,
                            last_error = NULL,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (revision, ProcessingStatus.PENDING, release_id)
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
        table_name: str = None,
        stac_item_id: str = None,
        content_hash: str = None,
        source_file_hash: str = None,
        output_file_hash: str = None
    ) -> bool:
        """
        Update physical output fields (dynamic -- only provided fields).

        Builds the SET clause dynamically from provided arguments.
        Always includes updated_at = NOW().

        Args:
            release_id: Release to update
            blob_path: Azure Blob Storage path for raster outputs
            table_name: PostGIS table name for vector outputs
            stac_item_id: STAC item identifier
            content_hash: Hash of processed output content
            source_file_hash: Hash of original source file
            output_file_hash: Hash of final output file

        Returns:
            True if updated, False if release not found or no fields provided
        """
        # Build dynamic SET clause from provided fields
        set_parts = []
        values = []

        field_map = {
            'blob_path': blob_path,
            'table_name': table_name,
            'stac_item_id': stac_item_id,
            'content_hash': content_hash,
            'source_file_hash': source_file_hash,
            'output_file_hash': output_file_hash,
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

                # Single commit for atomicity
                conn.commit()

                if target_updated:
                    logger.info(f"Flipped is_latest: asset {asset_id[:16]}... -> release {new_latest_release_id[:16]}...")
                else:
                    logger.warning(
                        f"flip_is_latest: target release {new_latest_release_id[:16]}... not found"
                    )

                return target_updated

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

        Parses enum fields from string values with try/except for safety.
        JSONB columns (stac_item_json, node_summary, platform_refs) are
        passed directly from the row -- psycopg3 returns them as dicts.

        Args:
            row: Database row as dict (from dict_row cursor)

        Returns:
            AssetRelease model instance
        """
        # Parse approval_state
        approval_state_value = row.get('approval_state', 'pending_review')
        try:
            approval_state = ApprovalState(approval_state_value) if approval_state_value else ApprovalState.PENDING_REVIEW
        except ValueError:
            approval_state = ApprovalState.PENDING_REVIEW

        # Parse clearance_state
        clearance_state_value = row.get('clearance_state', 'uncleared')
        try:
            clearance_state = ClearanceState(clearance_state_value) if clearance_state_value else ClearanceState.UNCLEARED
        except ValueError:
            clearance_state = ClearanceState.UNCLEARED

        # Parse processing_status
        processing_status_value = row.get('processing_status', 'pending')
        try:
            processing_status = ProcessingStatus(processing_status_value) if processing_status_value else ProcessingStatus.PENDING
        except ValueError:
            processing_status = ProcessingStatus.PENDING

        return AssetRelease(
            # Identity
            release_id=row['release_id'],
            asset_id=row['asset_id'],
            # Version
            version_id=row.get('version_id'),
            suggested_version_id=row.get('suggested_version_id'),
            version_ordinal=row.get('version_ordinal'),
            revision=row.get('revision', 1),
            previous_release_id=row.get('previous_release_id'),
            # Flags
            is_latest=row.get('is_latest', False),
            is_served=row.get('is_served', True),
            request_id=row.get('request_id'),
            # Physical outputs
            blob_path=row.get('blob_path'),
            table_name=row.get('table_name'),
            stac_item_id=row.get('stac_item_id', ''),
            stac_collection_id=row.get('stac_collection_id', ''),
            stac_item_json=row.get('stac_item_json'),
            content_hash=row.get('content_hash'),
            source_file_hash=row.get('source_file_hash'),
            output_file_hash=row.get('output_file_hash'),
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
