# ============================================================================
# GEOSPATIAL ASSET REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - GeospatialAsset CRUD operations
# PURPOSE: Database operations for app.geospatial_assets table
# LAST_REVIEWED: 29 JAN 2026
# EXPORTS: GeospatialAssetRepository
# DEPENDENCIES: psycopg, core.models.asset
# ============================================================================
"""
Geospatial Asset Repository.

Database operations for the geospatial asset entity system. Handles all
persistence for the geospatial_assets table (V0.8 Entity Architecture).

Features:
    - Advisory locks for concurrent request handling
    - Soft delete with audit trail
    - Upsert with revision tracking
    - State transition validation

Exports:
    GeospatialAssetRepository: CRUD operations for geospatial assets

Created: 29 JAN 2026 as part of V0.8 Entity Architecture
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from uuid import uuid4

from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from core.models.asset import (
    GeospatialAsset,
    AssetRevision,
    ApprovalState,
    ClearanceState,
    ProcessingStatus  # DAG Orchestration (29 JAN 2026)
)
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "AssetRepository")


class GeospatialAssetRepository(PostgreSQLRepository):
    """
    Repository for geospatial asset operations.

    Handles CRUD operations for app.geospatial_assets table.
    Uses advisory locks for concurrent request serialization.

    Table: app.geospatial_assets
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "geospatial_assets"
        self.schema = "app"

    # =========================================================================
    # UPSERT (Primary Creation/Update Pattern)
    # =========================================================================

    def upsert(
        self,
        asset_id: str,
        dataset_id: str,
        resource_id: str,
        version_id: str,
        data_type: str,
        stac_item_id: str,
        stac_collection_id: str,
        table_name: Optional[str] = None,
        blob_path: Optional[str] = None,
        overwrite: bool = False
    ) -> Tuple[str, int, Optional[str]]:
        """
        Upsert a geospatial asset using the database function.

        Uses advisory locks to serialize concurrent requests for the same asset.
        Returns operation result (created/updated/exists/reactivated).

        Args:
            asset_id: Deterministic ID from DDH identifiers
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier
            data_type: 'vector' or 'raster'
            stac_item_id: STAC item identifier
            stac_collection_id: STAC collection identifier
            table_name: PostGIS table name (for vectors)
            blob_path: Azure Blob path (for rasters)
            overwrite: If True, replace existing asset

        Returns:
            Tuple of (operation, new_revision, error_message)
            - operation: 'created', 'updated', 'exists', 'reactivated'
            - new_revision: Current revision number
            - error_message: None on success, error text on 'exists'
        """
        logger.info(f"Upserting asset: {asset_id} (overwrite={overwrite})")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.upsert_geospatial_asset(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """).format(sql.Identifier(self.schema)),
                    (
                        asset_id, dataset_id, resource_id, version_id,
                        data_type, stac_item_id, stac_collection_id,
                        table_name, blob_path, overwrite
                    )
                )
                result = cur.fetchone()
                conn.commit()

                operation = result['operation']
                new_revision = result['new_revision']
                error_message = result['error_message']

                if error_message:
                    logger.warning(f"Asset upsert blocked: {asset_id} - {error_message}")
                else:
                    logger.info(f"Asset upsert: {operation} {asset_id} at revision {new_revision}")

                return operation, new_revision, error_message

    # =========================================================================
    # CREATE (Direct Insert - use upsert() for normal operations)
    # =========================================================================

    def create(self, asset: GeospatialAsset) -> GeospatialAsset:
        """
        Create a new geospatial asset record directly.

        Note: Prefer upsert() for normal operations as it handles
        concurrency and revision tracking automatically.

        Args:
            asset: GeospatialAsset model to insert

        Returns:
            Created GeospatialAsset with timestamps

        Raises:
            ValueError: If asset_id already exists
        """
        logger.info(f"Creating asset directly: {asset.asset_id}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if already exists
                cur.execute(
                    sql.SQL("SELECT 1 FROM {}.{} WHERE asset_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset.asset_id,)
                )
                if cur.fetchone():
                    raise ValueError(f"Asset '{asset.asset_id}' already exists")

                now = datetime.now(timezone.utc)
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            asset_id, dataset_id, resource_id, version_id,
                            data_type, table_name, blob_path,
                            stac_item_id, stac_collection_id,
                            revision, current_job_id, content_hash,
                            approval_state, reviewer, reviewed_at, rejection_reason,
                            clearance_state, adf_run_id,
                            deleted_at, deleted_by,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        asset.asset_id, asset.dataset_id, asset.resource_id, asset.version_id,
                        asset.data_type, asset.table_name, asset.blob_path,
                        asset.stac_item_id, asset.stac_collection_id,
                        asset.revision, asset.current_job_id, asset.content_hash,
                        asset.approval_state.value if isinstance(asset.approval_state, ApprovalState) else asset.approval_state,
                        asset.reviewer, asset.reviewed_at, asset.rejection_reason,
                        asset.clearance_state.value if isinstance(asset.clearance_state, ClearanceState) else asset.clearance_state,
                        asset.adf_run_id,
                        asset.deleted_at, asset.deleted_by,
                        now, now
                    )
                )
                row = cur.fetchone()
                conn.commit()

                logger.info(f"Created asset: {asset.asset_id}")
                return self._row_to_model(row)

    # =========================================================================
    # READ
    # =========================================================================

    def get_by_id(self, asset_id: str) -> Optional[GeospatialAsset]:
        """
        Get an asset by ID (includes soft-deleted).

        Args:
            asset_id: Asset identifier

        Returns:
            GeospatialAsset if found, None otherwise
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
                return self._row_to_model(row) if row else None

    def get_active_by_id(self, asset_id: str) -> Optional[GeospatialAsset]:
        """
        Get an active (not deleted) asset by ID.

        Args:
            asset_id: Asset identifier

        Returns:
            GeospatialAsset if found and active, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s AND deleted_at IS NULL
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_identity(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> Optional[GeospatialAsset]:
        """
        Get an asset by DDH identity (dataset_id, resource_id, version_id).

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            GeospatialAsset if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE dataset_id = %s AND resource_id = %s AND version_id = %s
                          AND deleted_at IS NULL
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (dataset_id, resource_id, version_id)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_stac_item_id(self, stac_item_id: str) -> Optional[GeospatialAsset]:
        """
        Get an asset by STAC item ID.

        Args:
            stac_item_id: STAC item identifier

        Returns:
            GeospatialAsset if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE stac_item_id = %s AND deleted_at IS NULL
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (stac_item_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_job_id(self, job_id: str) -> Optional[GeospatialAsset]:
        """
        Get an asset by current job ID.

        Args:
            job_id: Job identifier

        Returns:
            GeospatialAsset if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE current_job_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (job_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def list_by_approval_state(
        self,
        state: ApprovalState,
        limit: int = 50,
        offset: int = 0
    ) -> List[GeospatialAsset]:
        """
        List assets by approval state.

        Args:
            state: Approval state to filter by
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of GeospatialAsset models
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE approval_state = %s AND deleted_at IS NULL
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (state.value, limit, offset)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_pending_review(self, limit: int = 50) -> List[GeospatialAsset]:
        """
        List assets pending review (convenience method).

        Args:
            limit: Maximum number of results

        Returns:
            List of pending GeospatialAsset models
        """
        return self.list_by_approval_state(ApprovalState.PENDING_REVIEW, limit=limit)

    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False
    ) -> List[GeospatialAsset]:
        """
        List all assets with optional filters.

        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            include_deleted: Include soft-deleted assets

        Returns:
            List of GeospatialAsset models
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                if include_deleted:
                    query = sql.SQL("""
                        SELECT * FROM {}.{}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """)
                    params = (limit, offset)
                else:
                    query = sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE deleted_at IS NULL
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """)
                    params = (limit, offset)

                cur.execute(
                    query.format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    params
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_by_platform_refs(
        self,
        platform_id: str,
        refs_filter: Dict[str, Any],
        limit: int = 100,
        offset: int = 0
    ) -> List[GeospatialAsset]:
        """
        List assets by platform and partial platform_refs (JSONB containment).

        Uses PostgreSQL JSONB containment operator (@>) for efficient queries.
        Requires GIN index on platform_refs for performance.

        V0.8 Enhancement (29 JAN 2026):
        - Enables queries like "all assets for dataset X" without knowing resource/version
        - Supports partial matching on any subset of platform_refs keys

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            refs_filter: Partial refs to match (e.g., {"dataset_id": "IDN_lulc"})
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of matching GeospatialAsset models

        Example:
            # Get all assets for a dataset (any resource/version)
            assets = repo.list_by_platform_refs("ddh", {"dataset_id": "IDN_lulc"})

            # Get all assets for a specific resource (any version)
            assets = repo.list_by_platform_refs("ddh", {
                "dataset_id": "IDN_lulc",
                "resource_id": "jakarta"
            })
        """
        import json

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE platform_id = %s
                          AND platform_refs @> %s
                          AND deleted_at IS NULL
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (platform_id, json.dumps(refs_filter), limit, offset)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def count_by_state(self) -> Dict[str, int]:
        """
        Count assets by approval state.

        Returns:
            Dictionary with state counts
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT approval_state, COUNT(*) as count
                        FROM {}.{}
                        WHERE deleted_at IS NULL
                        GROUP BY approval_state
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    )
                )
                rows = cur.fetchall()
                return {row['approval_state']: row['count'] for row in rows}

    # =========================================================================
    # UPDATE
    # =========================================================================

    def update(self, asset_id: str, updates: Dict[str, Any]) -> Optional[GeospatialAsset]:
        """
        Update an asset record.

        Args:
            asset_id: Asset to update
            updates: Dictionary of field updates

        Returns:
            Updated GeospatialAsset if found, None otherwise
        """
        if not updates:
            return self.get_by_id(asset_id)

        # Always update updated_at
        updates['updated_at'] = datetime.now(timezone.utc)

        # Convert enums to values
        if 'approval_state' in updates and isinstance(updates['approval_state'], ApprovalState):
            updates['approval_state'] = updates['approval_state'].value
        if 'clearance_state' in updates and isinstance(updates['clearance_state'], ClearanceState):
            updates['clearance_state'] = updates['clearance_state'].value
        if 'processing_status' in updates and isinstance(updates['processing_status'], ProcessingStatus):
            updates['processing_status'] = updates['processing_status'].value

        # Build SET clause
        set_parts = []
        values = []
        for key, value in updates.items():
            set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            values.append(value)

        values.append(asset_id)  # For WHERE clause

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("UPDATE {}.{} SET {} WHERE asset_id = %s RETURNING *").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.SQL(", ").join(set_parts)
                    ),
                    values
                )
                row = cur.fetchone()
                conn.commit()

                return self._row_to_model(row) if row else None

    def link_job(
        self,
        asset_id: str,
        job_id: str,
        content_hash: Optional[str] = None
    ) -> Optional[GeospatialAsset]:
        """
        Link a job to an asset and optionally set content hash.

        Called when a job starts processing an asset.

        Args:
            asset_id: Asset to update
            job_id: Job that is processing this asset
            content_hash: Optional content hash of source file

        Returns:
            Updated GeospatialAsset if found, None otherwise
        """
        updates = {'current_job_id': job_id}
        if content_hash:
            updates['content_hash'] = content_hash

        result = self.update(asset_id, updates)
        if result:
            logger.info(f"Linked job {job_id} to asset {asset_id}")
        return result

    def approve(
        self,
        asset_id: str,
        reviewer: str,
        clearance_level: ClearanceState,
        adf_run_id: Optional[str] = None
    ) -> Optional[GeospatialAsset]:
        """
        Approve an asset with specified clearance level.

        V0.8 Enhancement (29 JAN 2026):
        - Allows approval from PENDING_REVIEW (standard) or APPROVED (clearance change)
        - Tracks clearance audit columns (cleared_at/by, made_public_at/by)

        Args:
            asset_id: Asset to approve
            reviewer: Email of reviewer
            clearance_level: OUO or PUBLIC
            adf_run_id: ADF pipeline run ID (if PUBLIC)

        Returns:
            Updated GeospatialAsset if found, None otherwise

        Raises:
            ValueError: If asset is in REJECTED state
        """
        existing = self.get_active_by_id(asset_id)
        if not existing:
            return None

        # Allow PENDING_REVIEW (standard approval) or APPROVED (clearance change)
        if existing.approval_state == ApprovalState.REJECTED:
            raise ValueError(
                f"Cannot approve: asset {asset_id} is rejected. "
                f"Resubmit with overwrite=true to reset approval state."
            )

        now = datetime.now(timezone.utc)
        updates = {
            'approval_state': ApprovalState.APPROVED,
            'clearance_state': clearance_level,
            'reviewer': reviewer,
            'reviewed_at': now
        }
        if adf_run_id:
            updates['adf_run_id'] = adf_run_id

        # Track clearance audit trail (29 JAN 2026)
        old_clearance = existing.clearance_state

        # First time clearing (UNCLEARED -> something else)
        if old_clearance == ClearanceState.UNCLEARED and clearance_level != ClearanceState.UNCLEARED:
            updates['cleared_at'] = now
            updates['cleared_by'] = reviewer

        # Made public (anything -> PUBLIC)
        if clearance_level == ClearanceState.PUBLIC and old_clearance != ClearanceState.PUBLIC:
            updates['made_public_at'] = now
            updates['made_public_by'] = reviewer

        result = self.update(asset_id, updates)
        if result:
            if existing.approval_state == ApprovalState.APPROVED:
                logger.info(f"Clearance change for {asset_id}: {old_clearance.value} -> {clearance_level.value} by {reviewer}")
            else:
                logger.info(f"Approved asset {asset_id} by {reviewer} with clearance {clearance_level.value}")
        return result

    def reject(
        self,
        asset_id: str,
        reviewer: str,
        reason: str
    ) -> Optional[GeospatialAsset]:
        """
        Reject an asset.

        Args:
            asset_id: Asset to reject
            reviewer: Email of reviewer
            reason: Rejection reason (required)

        Returns:
            Updated GeospatialAsset if found, None otherwise

        Raises:
            ValueError: If asset is not in PENDING_REVIEW state or reason not provided
        """
        if not reason or not reason.strip():
            raise ValueError("Rejection reason is required")

        existing = self.get_active_by_id(asset_id)
        if not existing:
            return None

        if existing.approval_state != ApprovalState.PENDING_REVIEW:
            raise ValueError(
                f"Cannot reject: asset {asset_id} is in '{existing.approval_state}' state, not 'pending_review'"
            )

        updates = {
            'approval_state': ApprovalState.REJECTED,
            'reviewer': reviewer,
            'rejection_reason': reason,
            'reviewed_at': datetime.now(timezone.utc)
        }

        result = self.update(asset_id, updates)
        if result:
            logger.info(f"Rejected asset {asset_id} by {reviewer}: {reason}")
        return result

    # =========================================================================
    # SOFT DELETE
    # =========================================================================

    def soft_delete(
        self,
        asset_id: str,
        deleted_by: str
    ) -> Optional[GeospatialAsset]:
        """
        Soft delete an asset (preserves for audit trail).

        Args:
            asset_id: Asset to delete
            deleted_by: Who is deleting (user email or system)

        Returns:
            Updated GeospatialAsset if found, None otherwise
        """
        now = datetime.now(timezone.utc)
        updates = {
            'deleted_at': now,
            'deleted_by': deleted_by
        }

        result = self.update(asset_id, updates)
        if result:
            logger.warning(f"Soft deleted asset {asset_id} by {deleted_by}")
        return result

    def hard_delete(self, asset_id: str) -> bool:
        """
        Permanently delete an asset (use with caution).

        Args:
            asset_id: Asset to delete

        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DELETE FROM {}.{} WHERE asset_id = %s RETURNING asset_id").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id,)
                )
                deleted = cur.fetchone()
                conn.commit()

                if deleted:
                    logger.warning(f"Hard deleted asset: {asset_id}")
                return deleted is not None

    # =========================================================================
    # PROCESSING STATUS (DAG Orchestration - 29 JAN 2026)
    # =========================================================================

    def start_processing(
        self,
        asset_id: str,
        job_id: str,
        workflow_id: Optional[str] = None,
        workflow_version: Optional[int] = None,
        request_id: Optional[str] = None
    ) -> Optional[GeospatialAsset]:
        """
        Mark asset as processing (job started).

        Called by DAG orchestrator when job begins execution.
        Increments job_count for retry tracking.

        Args:
            asset_id: Asset to update
            job_id: Job that is processing this asset
            workflow_id: Workflow identifier (e.g., "raster_processing")
            workflow_version: Version of workflow for debugging
            request_id: Request ID for B2B callback routing

        Returns:
            Updated GeospatialAsset if found, None otherwise
        """
        now = datetime.now(timezone.utc)
        updates = {
            'current_job_id': job_id,
            'processing_status': ProcessingStatus.PROCESSING,
            'processing_started_at': now,
            'processing_completed_at': None,  # Reset if retrying
            'last_error': None  # Clear previous error
        }

        if workflow_id:
            updates['workflow_id'] = workflow_id
        if workflow_version:
            updates['workflow_version'] = workflow_version
        if request_id:
            updates['last_request_id'] = request_id

        # Increment job_count atomically
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET processing_status = %s,
                            processing_started_at = %s,
                            processing_completed_at = NULL,
                            last_error = NULL,
                            current_job_id = %s,
                            workflow_id = COALESCE(%s, workflow_id),
                            workflow_version = COALESCE(%s, workflow_version),
                            last_request_id = COALESCE(%s, last_request_id),
                            job_count = job_count + 1,
                            updated_at = %s
                        WHERE asset_id = %s
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        ProcessingStatus.PROCESSING.value,
                        now,
                        job_id,
                        workflow_id,
                        workflow_version,
                        request_id,
                        now,
                        asset_id
                    )
                )
                row = cur.fetchone()
                conn.commit()

                if row:
                    logger.info(f"Started processing asset {asset_id} with job {job_id}")
                    return self._row_to_model(row)
                return None

    def complete_processing(
        self,
        asset_id: str,
        output_file_hash: Optional[str] = None
    ) -> Optional[GeospatialAsset]:
        """
        Mark asset as completed (job succeeded).

        Called by DAG orchestrator when job finishes successfully.

        Args:
            asset_id: Asset to update
            output_file_hash: Optional SHA256 of output file for integrity

        Returns:
            Updated GeospatialAsset if found, None otherwise
        """
        now = datetime.now(timezone.utc)
        updates = {
            'processing_status': ProcessingStatus.COMPLETED,
            'processing_completed_at': now,
            'estimated_completion_at': None  # Clear ETA
        }

        if output_file_hash:
            updates['output_file_hash'] = output_file_hash

        result = self.update(asset_id, updates)
        if result:
            logger.info(f"Completed processing asset {asset_id}")
        return result

    def fail_processing(
        self,
        asset_id: str,
        error_message: str
    ) -> Optional[GeospatialAsset]:
        """
        Mark asset as failed (job failed).

        Called by DAG orchestrator when job fails.

        Args:
            asset_id: Asset to update
            error_message: Error message (truncated to 2000 chars)

        Returns:
            Updated GeospatialAsset if found, None otherwise
        """
        updates = {
            'processing_status': ProcessingStatus.FAILED,
            'last_error': error_message[:2000] if error_message else None,
            'estimated_completion_at': None  # Clear ETA
        }

        result = self.update(asset_id, updates)
        if result:
            logger.warning(f"Failed processing asset {asset_id}: {error_message[:100]}")
        return result

    def reset_for_retry(self, asset_id: str) -> Optional[GeospatialAsset]:
        """
        Reset asset to pending for retry.

        Called when submitting a retry request.

        Args:
            asset_id: Asset to reset

        Returns:
            Updated GeospatialAsset if found, None otherwise
        """
        updates = {
            'processing_status': ProcessingStatus.PENDING,
            'last_error': None
        }

        result = self.update(asset_id, updates)
        if result:
            logger.info(f"Reset asset {asset_id} for retry")
        return result

    def update_node_summary(
        self,
        asset_id: str,
        node_summary: Dict[str, Any],
        estimated_completion_at: Optional[datetime] = None
    ) -> Optional[GeospatialAsset]:
        """
        Update node progress summary (DAG workflow progress).

        Called periodically by DAG orchestrator to track progress.

        Args:
            asset_id: Asset to update
            node_summary: Progress info {total, completed, failed, current_node}
            estimated_completion_at: Optional ETA

        Returns:
            Updated GeospatialAsset if found, None otherwise
        """
        updates = {'node_summary': node_summary}
        if estimated_completion_at:
            updates['estimated_completion_at'] = estimated_completion_at

        return self.update(asset_id, updates)

    def list_by_processing_status(
        self,
        status: ProcessingStatus,
        limit: int = 100,
        offset: int = 0
    ) -> List[GeospatialAsset]:
        """
        List assets by processing status.

        Useful for monitoring dashboards and stuck job detection.

        Args:
            status: Processing status to filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of matching GeospatialAsset models
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE processing_status = %s
                          AND deleted_at IS NULL
                        ORDER BY updated_at DESC
                        LIMIT %s OFFSET %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (status.value, limit, offset)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_stuck_processing(self, older_than_hours: int = 1) -> List[GeospatialAsset]:
        """
        List assets stuck in processing state (SLA violation).

        Args:
            older_than_hours: How many hours to consider "stuck"

        Returns:
            List of stuck assets
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE processing_status = %s
                          AND processing_started_at < NOW() - INTERVAL '%s hours'
                          AND deleted_at IS NULL
                        ORDER BY processing_started_at ASC
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (ProcessingStatus.PROCESSING.value, older_than_hours)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_model(self, row: Dict[str, Any]) -> GeospatialAsset:
        """Convert database row to GeospatialAsset model."""
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

        # Parse processing_status (DAG Orchestration - 29 JAN 2026)
        processing_status_value = row.get('processing_status', 'pending')
        try:
            processing_status = ProcessingStatus(processing_status_value) if processing_status_value else ProcessingStatus.PENDING
        except ValueError:
            processing_status = ProcessingStatus.PENDING

        return GeospatialAsset(
            asset_id=row['asset_id'],
            dataset_id=row['dataset_id'],
            resource_id=row['resource_id'],
            version_id=row['version_id'],
            data_type=row['data_type'],
            table_name=row.get('table_name'),
            blob_path=row.get('blob_path'),
            stac_item_id=row['stac_item_id'],
            stac_collection_id=row['stac_collection_id'],
            revision=row['revision'],
            current_job_id=row.get('current_job_id'),
            content_hash=row.get('content_hash'),
            approval_state=approval_state,
            reviewer=row.get('reviewer'),
            reviewed_at=row.get('reviewed_at'),
            rejection_reason=row.get('rejection_reason'),
            clearance_state=clearance_state,
            adf_run_id=row.get('adf_run_id'),
            # Clearance audit trail (29 JAN 2026)
            cleared_at=row.get('cleared_at'),
            cleared_by=row.get('cleared_by'),
            made_public_at=row.get('made_public_at'),
            made_public_by=row.get('made_public_by'),
            deleted_at=row.get('deleted_at'),
            deleted_by=row.get('deleted_by'),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at'),
            # Platform Registry (29 JAN 2026)
            platform_id=row.get('platform_id', 'ddh'),
            platform_refs=row.get('platform_refs', {}),
            # DAG Orchestration (29 JAN 2026)
            workflow_id=row.get('workflow_id'),
            workflow_version=row.get('workflow_version'),
            job_count=row.get('job_count', 0),
            last_request_id=row.get('last_request_id'),
            processing_status=processing_status,
            processing_started_at=row.get('processing_started_at'),
            processing_completed_at=row.get('processing_completed_at'),
            last_error=row.get('last_error'),
            node_summary=row.get('node_summary'),
            priority=row.get('priority', 5),
            estimated_completion_at=row.get('estimated_completion_at'),
            source_file_hash=row.get('source_file_hash'),
            output_file_hash=row.get('output_file_hash')
        )

    def exists(self, asset_id: str) -> bool:
        """Check if an asset exists (including deleted)."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT 1 FROM {}.{} WHERE asset_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id,)
                )
                return cur.fetchone() is not None


# Module exports
__all__ = ['GeospatialAssetRepository']
