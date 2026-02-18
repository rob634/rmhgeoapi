# ============================================================================
# GEOSPATIAL ASSET SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - Business logic for geospatial assets
# PURPOSE: Orchestrate asset lifecycle: create, approve, reject, delete
# LAST_REVIEWED: 09 FEB 2026 (Approval-aware overwrite validation)
# EXPORTS: AssetService, AssetExistsError
# DEPENDENCIES: infrastructure.asset_repository, infrastructure.revision_repository
# ============================================================================
"""
Geospatial Asset Service - V0.8 Entity Architecture.

Business logic for the geospatial asset lifecycle. Handles:
- Creating assets when Platform API receives requests
- Approving assets (set clearance, optionally trigger ADF)
- Rejecting assets
- Soft deleting assets (audit trail preserved)
- Linking jobs to assets

This service coordinates:
- GeospatialAssetRepository for main entity CRUD
- AssetRevisionRepository for audit trail
- Future: PGSTACRepository for STAC item updates
- Future: AzureDataFactoryRepository for PUBLIC approval

Exports:
    AssetService: Business logic for asset lifecycle
    AssetExistsError: Raised when asset exists and overwrite=False

Created: 29 JAN 2026 as part of V0.8 Entity Architecture
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType
from core.models.asset import (
    GeospatialAsset,
    AssetRevision,
    ApprovalState,
    ClearanceState,
    ProcessingStatus  # DAG Orchestration (29 JAN 2026)
)
from infrastructure.asset_repository import GeospatialAssetRepository
from infrastructure.revision_repository import AssetRevisionRepository

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "AssetService")


class AssetExistsError(Exception):
    """Raised when asset already exists and overwrite=False."""

    def __init__(self, asset_id: str, platform_id: str, platform_refs: Dict[str, Any]):
        self.asset_id = asset_id
        self.platform_id = platform_id
        self.platform_refs = platform_refs
        super().__init__(
            f"Asset already exists for {platform_id}: {platform_refs}. "
            f"Use overwrite=True to replace. Existing asset_id: {asset_id}"
        )


class AssetNotFoundError(Exception):
    """Raised when asset not found for operation."""

    def __init__(self, identifier: str, identifier_type: str = "asset_id"):
        self.identifier = identifier
        self.identifier_type = identifier_type
        super().__init__(f"Asset not found: {identifier_type}={identifier}")


class AssetStateError(Exception):
    """Raised when asset is in invalid state for requested operation."""

    def __init__(self, asset_id: str, current_state: str, required_state: str, operation: str):
        self.asset_id = asset_id
        self.current_state = current_state
        self.required_state = required_state
        self.operation = operation
        super().__init__(
            f"Cannot {operation} asset {asset_id}: "
            f"current state is '{current_state}', requires '{required_state}'"
        )


class AssetService:
    """
    Service for managing geospatial asset lifecycle.

    Provides:
    - Asset creation with upsert semantics
    - Approval workflow (approve/reject)
    - Soft delete with audit trail
    - Job linking
    - Revision history

    V0.8 Migration (30 JAN 2026):
    - Changed from DDH-specific params to platform_id + platform_refs

    Usage:
        from services.asset_service import AssetService

        service = AssetService()

        # Create or update asset (V0.8 signature)
        result = service.create_or_update_asset(
            platform_id="ddh",
            platform_refs={
                "dataset_id": "flood-2024",
                "resource_id": "site-a",
                "version_id": "v1.0"
            },
            data_type="raster",
            stac_item_id="flood-2024-site-a-v10",
            stac_collection_id="flood-2024",
            overwrite=False
        )

        # Approve asset
        asset = service.approve(
            asset_id="abc123...",
            reviewer="user@example.com",
            clearance_level=ClearanceState.OUO
        )
    """

    def __init__(self):
        """Initialize with repository dependencies."""
        self._asset_repo = GeospatialAssetRepository()
        self._revision_repo = AssetRevisionRepository()

    # =========================================================================
    # CREATION
    # =========================================================================

    def create_or_update_asset(
        self,
        platform_id: str,
        platform_refs: Dict[str, Any],
        data_type: str,
        stac_item_id: str,
        stac_collection_id: str,
        table_name: Optional[str] = None,
        blob_path: Optional[str] = None,
        overwrite: bool = False,
        clearance_level: Optional[ClearanceState] = None,
        submitted_by: Optional[str] = None,
        # V0.8 Release Control: Lineage parameters (30 JAN 2026)
        lineage_id: Optional[str] = None,
        version_ordinal: Optional[int] = None,
        previous_asset_id: Optional[str] = None,
        is_latest: Optional[bool] = None,
        retire_versions: Optional[List[str]] = None
    ) -> Tuple[GeospatialAsset, str]:
        """
        Create a new asset or update existing with overwrite.

        V0.8 Migration (30 JAN 2026):
        - Changed from DDH-specific params to platform_id + platform_refs
        - Uses advisory locks via database function to handle concurrent requests

        V0.8 Release Control (30 JAN 2026):
        - Added lineage_id, version_ordinal, previous_asset_id, is_latest parameters
        - Handles is_latest flag flip when adding new version to lineage
        - Supports retire_versions to stop serving old versions

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            platform_refs: Platform-specific identifiers as dict
            data_type: 'vector' or 'raster'
            stac_item_id: STAC item identifier
            stac_collection_id: STAC collection identifier
            table_name: PostGIS table name (vectors only)
            blob_path: Azure Blob path (rasters only)
            overwrite: If True, replace existing asset
            clearance_level: Optional clearance level (default: UNCLEARED)
            submitted_by: Who submitted the request (for audit trail if clearance set)
            lineage_id: Lineage identifier for version grouping
            version_ordinal: B2B-provided version order (1, 2, 3...)
            previous_asset_id: FK to previous version in lineage
            is_latest: Whether this is the latest version (default: True)
            retire_versions: Optional list of version_ids to stop serving

        Returns:
            Tuple of (GeospatialAsset, operation) where operation is:
            - 'created': New asset created
            - 'updated': Existing asset replaced (overwrite)
            - 'reactivated': Soft-deleted asset restored

        Raises:
            AssetExistsError: If asset exists and overwrite=False
        """
        clearance_info = f", clearance={clearance_level.value}" if clearance_level else ""
        lineage_info = f", lineage={lineage_id}" if lineage_id else ""
        logger.info(
            f"Creating/updating asset for {platform_id}: {platform_refs} "
            f"(type={data_type}, overwrite={overwrite}{clearance_info}{lineage_info})"
        )

        # Generate deterministic asset_id
        asset_id = GeospatialAsset.generate_asset_id(platform_id, platform_refs)

        # V0.8.16.8: If this is a new version in an existing lineage, flip is_latest BEFORE insert
        # The unique constraint idx_single_latest_per_lineage requires only one is_latest=True per lineage.
        # We must clear is_latest on the current latest BEFORE inserting the new one.
        current_latest = None
        if lineage_id and (is_latest is None or is_latest):
            current_latest = self._asset_repo.get_latest_in_lineage(lineage_id)
            if current_latest and current_latest.asset_id != asset_id:
                # Flip is_latest BEFORE creating new asset to avoid unique constraint violation
                self._asset_repo.update(current_latest.asset_id, {'is_latest': False})
                logger.info(f"Cleared is_latest on {current_latest.asset_id} (preparing for {asset_id})")

        # Use upsert function (handles advisory locks internally)
        operation, new_revision, error_message = self._asset_repo.upsert(
            asset_id=asset_id,
            platform_id=platform_id,
            platform_refs=platform_refs,
            data_type=data_type,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            table_name=table_name,
            blob_path=blob_path,
            overwrite=overwrite,
            # V0.8 Release Control parameters
            lineage_id=lineage_id,
            version_ordinal=version_ordinal,
            previous_asset_id=previous_asset_id,
            is_latest=is_latest if is_latest is not None else True
        )

        if error_message:
            # Asset exists and overwrite=False
            raise AssetExistsError(asset_id, platform_id, platform_refs)

        # V0.8.16.8: is_latest flip now happens BEFORE upsert (see above)
        # No post-upsert flip needed since we cleared it before insert

        # Fetch the created/updated asset
        asset = self._asset_repo.get_by_id(asset_id)
        if not asset:
            raise RuntimeError(f"Asset {asset_id} not found after upsert (operation={operation})")

        # NOTE: Approval state reset for overwrite of REJECTED/REVOKED assets
        # is handled by the job handler AFTER successful completion, not here.
        # See reset_approval_for_overwrite() method.

        # Apply optional clearance level if provided at submit time
        # This is rare - most assets start as UNCLEARED and are cleared at approval
        if clearance_level and clearance_level != ClearanceState.UNCLEARED:
            from datetime import datetime, timezone
            updates = {
                'clearance_state': clearance_level.value,
                'cleared_at': datetime.now(timezone.utc),
                'cleared_by': submitted_by or 'system',
            }
            # Track made_public separately
            if clearance_level == ClearanceState.PUBLIC:
                updates['made_public_at'] = datetime.now(timezone.utc)
                updates['made_public_by'] = submitted_by or 'system'

            self._asset_repo.update(asset_id, updates)
            asset = self._asset_repo.get_by_id(asset_id)
            logger.info(f"Applied clearance_level={clearance_level.value} at submit time")

        # Handle version retirement
        if retire_versions and lineage_id:
            retired = self.retire_versions(lineage_id, retire_versions)
            if retired:
                logger.info(f"Retired {len(retired)} versions: {retire_versions}")

        logger.info(f"Asset {operation}: {asset_id} at revision {new_revision}")
        return asset, operation

    def get_or_create_asset(
        self,
        platform_id: str,
        platform_refs: Dict[str, Any],
        data_type: str,
        stac_item_id: str,
        stac_collection_id: str,
        table_name: Optional[str] = None,
        blob_path: Optional[str] = None
    ) -> Tuple[GeospatialAsset, bool]:
        """
        Get existing asset or create new one.

        Idempotent - safe to call multiple times.

        V0.8 Migration (30 JAN 2026):
        - Changed from DDH-specific params to platform_id + platform_refs

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            platform_refs: Platform-specific identifiers as dict
            data_type: 'vector' or 'raster'
            stac_item_id: STAC item identifier
            stac_collection_id: STAC collection identifier
            table_name: PostGIS table name (vectors only)
            blob_path: Azure Blob path (rasters only)

        Returns:
            Tuple of (GeospatialAsset, created) where created is True if new
        """
        # Check if asset exists
        asset_id = GeospatialAsset.generate_asset_id(platform_id, platform_refs)
        existing = self._asset_repo.get_active_by_id(asset_id)

        if existing:
            logger.debug(f"Found existing asset: {asset_id}")
            return existing, False

        # Create new asset
        asset, _ = self.create_or_update_asset(
            platform_id=platform_id,
            platform_refs=platform_refs,
            data_type=data_type,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            table_name=table_name,
            blob_path=blob_path,
            overwrite=False
        )
        return asset, True

    # =========================================================================
    # READ
    # =========================================================================

    def get_asset(self, asset_id: str) -> Optional[GeospatialAsset]:
        """Get an asset by ID (includes soft-deleted)."""
        return self._asset_repo.get_by_id(asset_id)

    def get_active_asset(self, asset_id: str) -> Optional[GeospatialAsset]:
        """Get an active (not deleted) asset by ID."""
        return self._asset_repo.get_active_by_id(asset_id)

    def get_asset_by_platform_refs(
        self,
        platform_id: str,
        platform_refs: Dict[str, Any]
    ) -> Optional[GeospatialAsset]:
        """
        Get an asset by exact platform_refs match.

        V0.8 Migration (30 JAN 2026):
        - Replaces get_asset_by_identity() which used DDH columns

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            platform_refs: Exact platform_refs to match

        Returns:
            GeospatialAsset if found, None otherwise
        """
        return self._asset_repo.get_by_platform_refs_exact(platform_id, platform_refs)

    def get_asset_by_stac_item(self, stac_item_id: str) -> Optional[GeospatialAsset]:
        """Get an asset by STAC item ID."""
        return self._asset_repo.get_by_stac_item_id(stac_item_id)

    def get_asset_by_job(self, job_id: str) -> Optional[GeospatialAsset]:
        """Get an asset linked to a job."""
        return self._asset_repo.get_by_job_id(job_id)

    def list_pending_review(self, limit: int = 50) -> List[GeospatialAsset]:
        """List assets pending review."""
        return self._asset_repo.list_pending_review(limit=limit)

    def list_assets(
        self,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False
    ) -> List[GeospatialAsset]:
        """List all assets with optional filters."""
        return self._asset_repo.list_all(
            limit=limit,
            offset=offset,
            include_deleted=include_deleted
        )

    def get_state_counts(self) -> Dict[str, int]:
        """Get counts of assets by approval state."""
        return self._asset_repo.count_by_state()

    def list_by_platform_refs(
        self,
        platform_id: str,
        refs_filter: Dict[str, Any],
        limit: int = 100,
        offset: int = 0
    ) -> List[GeospatialAsset]:
        """
        List assets by platform and partial platform_refs.

        V0.8 Enhancement (29 JAN 2026):
        - Enables queries like "all assets for dataset X" without knowing resource/version
        - Uses PostgreSQL JSONB containment operator (@>) for efficient queries

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            refs_filter: Partial refs to match (e.g., {"dataset_id": "IDN_lulc"})
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of matching GeospatialAsset models

        Example:
            # Get all assets for a dataset (any resource/version)
            assets = asset_service.list_by_platform_refs("ddh", {"dataset_id": "IDN_lulc"})
        """
        return self._asset_repo.list_by_platform_refs(
            platform_id=platform_id,
            refs_filter=refs_filter,
            limit=limit,
            offset=offset
        )

    # =========================================================================
    # JOB LINKING
    # =========================================================================

    def link_job_to_asset(
        self,
        asset_id: str,
        job_id: str,
        content_hash: Optional[str] = None
    ) -> GeospatialAsset:
        """
        Link a job to an asset.

        Called when a job starts processing an asset.

        Args:
            asset_id: Asset to link
            job_id: Job that is processing this asset
            content_hash: Optional content hash of source file

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.link_job(asset_id, job_id, content_hash)
        if not asset:
            raise AssetNotFoundError(asset_id)

        logger.info(f"Linked job {job_id} to asset {asset_id}")
        return asset

    def link_job_by_platform_refs(
        self,
        platform_id: str,
        platform_refs: Dict[str, Any],
        job_id: str,
        content_hash: Optional[str] = None
    ) -> GeospatialAsset:
        """
        Link a job to an asset by platform_refs.

        V0.8 Migration (30 JAN 2026):
        - Replaces link_job_by_identity() which used DDH columns

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            platform_refs: Platform-specific identifiers
            job_id: Job that is processing this asset
            content_hash: Optional content hash of source file

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.get_by_platform_refs_exact(platform_id, platform_refs)
        if not asset:
            raise AssetNotFoundError(
                f"{platform_id}: {platform_refs}",
                "platform_refs"
            )

        return self.link_job_to_asset(asset.asset_id, job_id, content_hash)

    # =========================================================================
    # APPROVAL WORKFLOW
    # =========================================================================

    def approve(
        self,
        asset_id: str,
        reviewer: str,
        clearance_level: ClearanceState,
        adf_run_id: Optional[str] = None
    ) -> Tuple[GeospatialAsset, Optional[str]]:
        """
        Approve an asset with specified clearance level, or change clearance on approved asset.

        V0.8 Enhancement (29 JAN 2026):
        - Allows approval from PENDING_REVIEW state (standard workflow)
        - Allows re-approval from APPROVED state to change clearance level
          - Use case: "Data was internal, later got permission to share publicly"
          - Downgrade (public→ouo) returns warning about manual ADF reversal

        For PUBLIC clearance, caller should trigger ADF first and pass run_id.

        Args:
            asset_id: Asset to approve
            reviewer: Email of reviewer
            clearance_level: OUO or PUBLIC
            adf_run_id: ADF pipeline run ID (if PUBLIC)

        Returns:
            Tuple of (GeospatialAsset, warning_message)
            - warning_message is set when downgrading from PUBLIC

        Raises:
            AssetNotFoundError: If asset not found
            AssetStateError: If asset is in REJECTED state (must resubmit)
        """
        existing = self._asset_repo.get_active_by_id(asset_id)
        if not existing:
            raise AssetNotFoundError(asset_id)

        warning = None

        # Check valid approval states
        if existing.approval_state == ApprovalState.REJECTED:
            raise AssetStateError(
                asset_id,
                existing.approval_state.value,
                "pending_review or approved",
                "approve (rejected assets must be resubmitted with overwrite=true)"
            )

        # Handle clearance change on already-approved asset
        if existing.approval_state == ApprovalState.APPROVED:
            old_clearance = existing.clearance_state
            if old_clearance == clearance_level:
                # No change needed
                logger.info(f"Asset {asset_id} already approved with clearance {clearance_level.value}")
                return existing, None

            # Downgrade warning (public → ouo)
            if old_clearance == ClearanceState.PUBLIC and clearance_level != ClearanceState.PUBLIC:
                warning = (
                    "Asset downgraded from PUBLIC. External zone data must be removed "
                    "via separate ADF reversal process (not yet automated)."
                )
                logger.warning(f"CLEARANCE DOWNGRADE: {asset_id} from PUBLIC to {clearance_level.value}")

            logger.info(
                f"Clearance change for approved asset {asset_id}: "
                f"{old_clearance.value} → {clearance_level.value}"
            )

        asset = self._asset_repo.approve(
            asset_id=asset_id,
            reviewer=reviewer,
            clearance_level=clearance_level,
            adf_run_id=adf_run_id
        )

        logger.info(
            f"Approved asset {asset_id} by {reviewer} "
            f"with clearance {clearance_level.value}"
        )
        return asset, warning

    def reject(
        self,
        asset_id: str,
        reviewer: str,
        reason: str
    ) -> GeospatialAsset:
        """
        Reject an asset.

        Args:
            asset_id: Asset to reject
            reviewer: Email of reviewer
            reason: Rejection reason (required)

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
            AssetStateError: If asset is not in PENDING_REVIEW state
            ValueError: If reason not provided
        """
        if not reason or not reason.strip():
            raise ValueError("Rejection reason is required")

        existing = self._asset_repo.get_active_by_id(asset_id)
        if not existing:
            raise AssetNotFoundError(asset_id)

        if existing.approval_state != ApprovalState.PENDING_REVIEW:
            raise AssetStateError(
                asset_id,
                existing.approval_state.value,
                ApprovalState.PENDING_REVIEW.value,
                "reject"
            )

        asset = self._asset_repo.reject(
            asset_id=asset_id,
            reviewer=reviewer,
            reason=reason
        )

        logger.info(f"Rejected asset {asset_id} by {reviewer}: {reason}")
        return asset

    # =========================================================================
    # DELETION
    # =========================================================================

    def soft_delete(
        self,
        asset_id: str,
        deleted_by: str
    ) -> GeospatialAsset:
        """
        Soft delete an asset (preserves for audit trail).

        Args:
            asset_id: Asset to delete
            deleted_by: Who is deleting (user email or system)

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.soft_delete(asset_id, deleted_by)
        if not asset:
            raise AssetNotFoundError(asset_id)

        logger.warning(f"Soft deleted asset {asset_id} by {deleted_by}")
        return asset

    def soft_delete_by_platform_refs(
        self,
        platform_id: str,
        platform_refs: Dict[str, Any],
        deleted_by: str
    ) -> GeospatialAsset:
        """
        Soft delete an asset by platform_refs.

        V0.8 Migration (30 JAN 2026):
        - Replaces soft_delete_by_identity() which used DDH columns

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            platform_refs: Platform-specific identifiers
            deleted_by: Who is deleting

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.get_by_platform_refs_exact(platform_id, platform_refs)
        if not asset:
            raise AssetNotFoundError(
                f"{platform_id}: {platform_refs}",
                "platform_refs"
            )

        return self.soft_delete(asset.asset_id, deleted_by)

    # =========================================================================
    # REVISION HISTORY
    # =========================================================================

    def get_revision_history(
        self,
        asset_id: str,
        limit: int = 50
    ) -> List[AssetRevision]:
        """
        Get revision history for an asset.

        Args:
            asset_id: Asset identifier
            limit: Maximum number of revisions

        Returns:
            List of AssetRevision records ordered by revision descending
        """
        return self._revision_repo.list_by_asset(asset_id, limit=limit)

    def get_specific_revision(
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
        return self._revision_repo.get_by_asset_and_revision(asset_id, revision)

    def count_revisions(self, asset_id: str) -> int:
        """Count total revisions for an asset."""
        return self._revision_repo.count_revisions(asset_id)

    # =========================================================================
    # PROCESSING LIFECYCLE (DAG Orchestration - 29 JAN 2026)
    # =========================================================================

    def start_processing(
        self,
        asset_id: str,
        job_id: str,
        workflow_id: Optional[str] = None,
        workflow_version: Optional[int] = None,
        request_id: Optional[str] = None
    ) -> GeospatialAsset:
        """
        Mark asset as processing (job started).

        Called by DAG orchestrator when job begins execution.
        This is the entry point for the processing state dimension.

        Args:
            asset_id: Asset to update
            job_id: Job that is processing this asset
            workflow_id: Workflow identifier (e.g., "raster_processing")
            workflow_version: Version of workflow for debugging
            request_id: Request ID for B2B callback routing

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.start_processing(
            asset_id=asset_id,
            job_id=job_id,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            request_id=request_id
        )
        if not asset:
            raise AssetNotFoundError(asset_id)

        logger.info(
            f"Started processing: asset={asset_id}, job={job_id}, "
            f"workflow={workflow_id}, job_count={asset.job_count}"
        )
        return asset

    def complete_processing(
        self,
        asset_id: str,
        output_file_hash: Optional[str] = None
    ) -> GeospatialAsset:
        """
        Mark asset as completed (job succeeded).

        Called by DAG orchestrator when job finishes successfully.

        Args:
            asset_id: Asset to update
            output_file_hash: Optional SHA256 of output file for integrity

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.complete_processing(asset_id, output_file_hash)
        if not asset:
            raise AssetNotFoundError(asset_id)

        logger.info(f"Completed processing: asset={asset_id}")
        return asset

    def fail_processing(
        self,
        asset_id: str,
        error_message: str
    ) -> GeospatialAsset:
        """
        Mark asset as failed (job failed).

        Called by DAG orchestrator when job fails.

        Args:
            asset_id: Asset to update
            error_message: Error message for debugging

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.fail_processing(asset_id, error_message)
        if not asset:
            raise AssetNotFoundError(asset_id)

        logger.warning(f"Failed processing: asset={asset_id}, error={error_message[:100]}")
        return asset

    def reset_for_retry(self, asset_id: str) -> GeospatialAsset:
        """
        Reset asset to pending for retry.

        Called when submitting a retry request.

        Args:
            asset_id: Asset to reset

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.reset_for_retry(asset_id)
        if not asset:
            raise AssetNotFoundError(asset_id)

        logger.info(f"Reset for retry: asset={asset_id}")
        return asset

    def update_node_summary(
        self,
        asset_id: str,
        node_summary: Dict[str, Any],
        estimated_completion_at: Optional[datetime] = None
    ) -> GeospatialAsset:
        """
        Update node progress summary (DAG workflow progress).

        Called periodically by DAG orchestrator to track progress.

        Args:
            asset_id: Asset to update
            node_summary: Progress info {total, completed, failed, current_node}
            estimated_completion_at: Optional ETA

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.update_node_summary(
            asset_id, node_summary, estimated_completion_at
        )
        if not asset:
            raise AssetNotFoundError(asset_id)

        return asset

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
        return self._asset_repo.list_by_processing_status(status, limit, offset)

    def list_stuck_processing(self, older_than_hours: int = 1) -> List[GeospatialAsset]:
        """
        List assets stuck in processing state (SLA violation).

        Args:
            older_than_hours: How many hours to consider "stuck"

        Returns:
            List of stuck assets
        """
        return self._asset_repo.list_stuck_processing(older_than_hours)

    # =========================================================================
    # LINEAGE QUERIES (V0.8 Release Control - 30 JAN 2026)
    # =========================================================================

    def get_latest_in_lineage(self, lineage_id: str) -> Optional[GeospatialAsset]:
        """
        Get the latest version of an asset lineage.

        V0.8 Release Control (30 JAN 2026):
        Used by Service Layer to resolve /latest URLs.

        Args:
            lineage_id: Lineage identifier (hash of platform_id + nominal refs)

        Returns:
            GeospatialAsset if found, None otherwise
        """
        return self._asset_repo.get_latest_in_lineage(lineage_id)

    def get_asset_by_version(
        self,
        lineage_id: str,
        version_id: str
    ) -> Optional[GeospatialAsset]:
        """
        Get a specific version of an asset by version_id.

        V0.8 Release Control (30 JAN 2026):
        Used by Service Layer to resolve /v1.0 URLs.

        Args:
            lineage_id: Lineage identifier
            version_id: Version identifier from platform_refs (e.g., "v1.0")

        Returns:
            GeospatialAsset if found and served, None otherwise
        """
        return self._asset_repo.get_by_version(lineage_id, version_id)

    def get_version_history(
        self,
        lineage_id: str,
        include_retired: bool = False
    ) -> List[GeospatialAsset]:
        """
        Get all versions in a lineage ordered by version_ordinal.

        V0.8 Release Control (30 JAN 2026):
        Used by /versions endpoint to list available versions.

        Args:
            lineage_id: Lineage identifier
            include_retired: If True, include is_served=FALSE versions

        Returns:
            List of GeospatialAsset models ordered by version_ordinal DESC
        """
        return self._asset_repo.get_version_history(lineage_id, include_retired)

    def reset_approval_for_overwrite(self, asset_id: str) -> bool:
        """
        Reset approval state to PENDING_REVIEW after successful overwrite.

        V0.8.16.7 (10 FEB 2026):
        Called by handlers AFTER job completes successfully when overwriting
        a REJECTED or REVOKED asset. This ensures approval state is only reset
        when new data actually exists.

        Args:
            asset_id: Asset to reset

        Returns:
            True if reset was performed, False if not needed or asset not found
        """
        asset = self._asset_repo.get_by_id(asset_id)
        if not asset:
            logger.warning(f"reset_approval_for_overwrite: asset {asset_id[:16]} not found")
            return False

        # Only reset if currently REJECTED or REVOKED
        if asset.approval_state not in (ApprovalState.REJECTED, ApprovalState.REVOKED):
            logger.debug(
                f"reset_approval_for_overwrite: asset {asset_id[:16]} is {asset.approval_state.value}, "
                f"no reset needed"
            )
            return False

        old_state = asset.approval_state.value
        reset_updates = {
            'approval_state': ApprovalState.PENDING_REVIEW,
            'reviewer': None,
            'reviewed_at': None,
            'rejection_reason': None,
            'revoked_at': None,
            'revoked_by': None,
            'revocation_reason': None,
            # Reset clearance to UNCLEARED for fresh review
            'clearance_state': ClearanceState.UNCLEARED,
            'cleared_at': None,
            'cleared_by': None,
            'made_public_at': None,
            'made_public_by': None,
            'adf_run_id': None
        }
        self._asset_repo.update(asset_id, reset_updates)
        logger.info(
            f"Reset approval state from {old_state} to pending_review for {asset_id[:16]} "
            f"after successful overwrite"
        )
        return True

    def get_lineage_state(
        self,
        platform_id: str,
        platform_refs: Dict[str, Any],
        nominal_refs: List[str]
    ) -> Dict[str, Any]:
        """
        Get lineage state for validate endpoint.

        V0.8 Release Control (30 JAN 2026):
        Used by /api/platform/validate to check lineage state before submit.

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            platform_refs: Full platform refs (including version)
            nominal_refs: List of nominal ref keys (e.g., ["dataset_id", "resource_id"])

        Returns:
            Dict with:
            - lineage_exists: bool
            - lineage_id: str
            - current_latest: Optional[dict] with version info
            - version_history: List of version summaries
            - version_exists: bool (if requested version already exists)
            - existing_asset: Optional[dict] if version exists
            - suggested_action: str
            - suggested_params: dict with version_ordinal and previous_version_id
        """
        # Generate lineage_id from nominal refs only
        lineage_id = GeospatialAsset.generate_lineage_id(platform_id, platform_refs, nominal_refs)

        # Check if requested version already exists
        version_id = platform_refs.get('version_id')
        existing_version = None
        if version_id:
            existing_version = self._asset_repo.get_by_version(lineage_id, version_id)

        # Get current latest
        current_latest = self._asset_repo.get_latest_in_lineage(lineage_id)

        # Get version history
        version_history = self._asset_repo.get_version_history(lineage_id, include_retired=True)

        # Build response
        result = {
            'lineage_id': lineage_id,
            'lineage_exists': len(version_history) > 0,
            'current_latest': None,
            'version_history': [],
            'version_exists': existing_version is not None,
            'existing_asset': None,
            'suggested_action': 'submit_new',
            'suggested_params': {
                'version_ordinal': 1,
                'previous_version_id': None
            },
            'warnings': []
        }

        if existing_version:
            result['existing_asset'] = {
                'version_id': existing_version.platform_refs.get('version_id'),
                'asset_id': existing_version.asset_id,
                'processing_status': existing_version.processing_status.value if hasattr(existing_version.processing_status, 'value') else existing_version.processing_status,
                # V0.8.16: Include approval_state for overwrite validation (09 FEB 2026)
                'approval_state': existing_version.approval_state.value if hasattr(existing_version.approval_state, 'value') else existing_version.approval_state,
                'is_latest': existing_version.is_latest,
                'is_served': existing_version.is_served
            }
            result['suggested_action'] = 'use_overwrite_or_change_version'
            result['warnings'].append(
                f"Version {version_id} already exists. Use overwrite=true to replace."
            )

        if current_latest:
            result['current_latest'] = {
                'version_id': current_latest.platform_refs.get('version_id'),
                'version_ordinal': current_latest.version_ordinal,
                'asset_id': current_latest.asset_id,
                'is_served': current_latest.is_served,
                # V0.8.16: Include approval_state for semantic version validation (09 FEB 2026)
                'approval_state': current_latest.approval_state.value if hasattr(current_latest.approval_state, 'value') else current_latest.approval_state,
                'created_at': current_latest.created_at.isoformat() if current_latest.created_at else None
            }

            if not existing_version:
                result['suggested_action'] = 'submit_new_version'
                result['suggested_params'] = {
                    'version_ordinal': current_latest.version_ordinal + 1,
                    'previous_version_id': current_latest.platform_refs.get('version_id')
                }

        # Build version history summary
        for asset in version_history:
            result['version_history'].append({
                'version_id': asset.platform_refs.get('version_id'),
                'ordinal': asset.version_ordinal,
                'is_latest': asset.is_latest,
                'is_served': asset.is_served
            })

        return result

    def flip_is_latest(
        self,
        old_asset_id: str,
        new_asset_id: str
    ) -> bool:
        """
        Atomically flip is_latest from old asset to new asset.

        V0.8 Release Control (30 JAN 2026):
        Called when submitting a new version to a lineage.

        Args:
            old_asset_id: Current latest asset (will become is_latest=FALSE)
            new_asset_id: New asset (will become is_latest=TRUE)

        Returns:
            True if both updates succeeded, False otherwise
        """
        return self._asset_repo.flip_is_latest(old_asset_id, new_asset_id)

    def update_is_served(
        self,
        asset_id: str,
        is_served: bool
    ) -> GeospatialAsset:
        """
        Update is_served flag for version retirement.

        V0.8 Release Control (30 JAN 2026):
        Called to retire/restore versions.

        Args:
            asset_id: Asset to update
            is_served: New is_served value

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
        """
        asset = self._asset_repo.update_is_served(asset_id, is_served)
        if not asset:
            raise AssetNotFoundError(asset_id)
        return asset

    def retire_versions(
        self,
        lineage_id: str,
        version_ids: List[str]
    ) -> List[GeospatialAsset]:
        """
        Retire multiple versions in a lineage.

        V0.8 Release Control (30 JAN 2026):
        Stops serving old versions while preserving data.

        Args:
            lineage_id: Lineage identifier
            version_ids: List of version_ids to retire

        Returns:
            List of updated GeospatialAsset models
        """
        retired = []
        for version_id in version_ids:
            asset = self._asset_repo.get_by_version(lineage_id, version_id)
            if asset:
                updated = self._asset_repo.update_is_served(asset.asset_id, False)
                if updated:
                    retired.append(updated)
                    logger.info(f"Retired version {version_id} in lineage {lineage_id}")
        return retired

    def generate_lineage_id(
        self,
        platform_id: str,
        platform_refs: Dict[str, Any],
        nominal_refs: List[str]
    ) -> str:
        """
        Generate lineage ID from nominal refs only.

        V0.8 Release Control (30 JAN 2026):
        Groups assets by their stable identity (without version).

        Args:
            platform_id: Platform identifier
            platform_refs: Full platform refs
            nominal_refs: Keys that form stable identity

        Returns:
            32-character lineage ID hash
        """
        return GeospatialAsset.generate_lineage_id(platform_id, platform_refs, nominal_refs)

    # =========================================================================
    # VERSION ASSIGNMENT (Draft Mode - 17 FEB 2026)
    # =========================================================================

    def assign_version(
        self,
        asset_id: str,
        version_id: str,
        previous_version_id: Optional[str] = None,
    ) -> GeospatialAsset:
        """
        Assign a version_id to a draft asset at approval time.

        Draft mode (17 FEB 2026): Assets submitted without version_id are
        "drafts". At approve/ time, the reviewer provides version_id (and
        previous_version_id for lineage chaining). This method:

        1. Validates asset exists and is a draft (no version_id in platform_refs)
        2. Runs lineage validation (reuses validate_version_lineage)
        3. Updates platform_refs with version_id
        4. Wires lineage: version_ordinal, previous_asset_id, is_latest flip
        5. Rebuilds stac_item_id and table_name with version_id
        6. Returns updated asset

        Args:
            asset_id: Asset to assign version to
            version_id: Version identifier (e.g., "v1.0")
            previous_version_id: Previous version for lineage chaining (None for first version)

        Returns:
            Updated GeospatialAsset

        Raises:
            AssetNotFoundError: If asset not found
            AssetStateError: If asset already has a version_id (not a draft)
            ValueError: If lineage validation fails
        """
        from services.platform_validation import validate_version_lineage
        from services.platform_translation import generate_stac_item_id, generate_table_name

        # 1. Fetch and validate asset is a draft
        asset = self._asset_repo.get_active_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError(asset_id)

        existing_version = asset.platform_refs.get('version_id')
        if existing_version:
            raise AssetStateError(
                asset_id,
                f"versioned ({existing_version})",
                "draft (no version_id)",
                "assign_version"
            )

        # 2. Build updated platform_refs with version_id
        updated_refs = dict(asset.platform_refs)
        updated_refs['version_id'] = version_id

        # 3. Run lineage validation (same logic as submit, now at approve time)
        validation_result = validate_version_lineage(
            platform_id=asset.platform_id,
            platform_refs=updated_refs,
            previous_version_id=previous_version_id,
            asset_service=self,
            overwrite=False
        )

        if not validation_result.valid:
            # Draft seeing itself as "current_latest" is expected — bypass (18 FEB 2026)
            # Check for both None and "" (empty string) as draft indicators
            draft_self_conflict = (
                validation_result.current_latest
                and validation_result.current_latest.get('asset_id') == asset_id
                and not validation_result.current_latest.get('version_id')
            )
            if draft_self_conflict:
                logger.info(
                    f"assign_version: draft {asset_id[:16]} sees itself in lineage, "
                    f"proceeding as first version"
                )
            else:
                raise ValueError(
                    f"Version lineage validation failed: {validation_result.warnings[0]}"
                )

        # 4. Compute lineage wiring
        lineage_id = validation_result.lineage_id
        version_ordinal = validation_result.suggested_params.get('version_ordinal', 1)
        previous_asset_id = None
        if validation_result.current_latest:
            previous_asset_id = validation_result.current_latest.get('asset_id')

        # 5. Flip is_latest on current latest before we update this asset
        if previous_asset_id and previous_asset_id != asset_id:
            current_latest = self._asset_repo.get_latest_in_lineage(lineage_id)
            if current_latest and current_latest.asset_id != asset_id:
                self._asset_repo.update(current_latest.asset_id, {'is_latest': False})
                logger.info(
                    f"assign_version: cleared is_latest on {current_latest.asset_id[:16]} "
                    f"for lineage {lineage_id[:16]}"
                )

        # 6. Rebuild stac_item_id and table_name with version_id
        dataset_id = asset.platform_refs.get('dataset_id', '')
        resource_id = asset.platform_refs.get('resource_id', '')
        new_stac_item_id = generate_stac_item_id(dataset_id, resource_id, version_id)
        new_table_name = None
        if asset.data_type == 'vector':
            new_table_name = generate_table_name(dataset_id, resource_id, version_id)

        # 7. Atomic update of all version-related fields
        update_fields = {
            'platform_refs': updated_refs,
            'lineage_id': lineage_id,
            'version_ordinal': version_ordinal,
            'previous_asset_id': previous_asset_id,
            'is_latest': True,
            'stac_item_id': new_stac_item_id,
        }
        if new_table_name:
            update_fields['table_name'] = new_table_name

        self._asset_repo.update(asset_id, update_fields)

        # 8. Re-fetch and return
        updated_asset = self._asset_repo.get_by_id(asset_id)
        logger.info(
            f"assign_version: {asset_id[:16]} → version_id={version_id}, "
            f"ordinal={version_ordinal}, stac_item_id={new_stac_item_id}, "
            f"lineage={lineage_id[:16]}"
        )
        return updated_asset

    # =========================================================================
    # UTILITY
    # =========================================================================

    def exists(self, asset_id: str) -> bool:
        """Check if an asset exists (including deleted)."""
        return self._asset_repo.exists(asset_id)

    def generate_asset_id(
        self,
        platform_id: str,
        platform_refs: Dict[str, Any]
    ) -> str:
        """
        Generate deterministic asset ID from platform identifiers.

        V0.8 Migration (30 JAN 2026):
        - Changed signature to use platform_id + platform_refs
        """
        return GeospatialAsset.generate_asset_id(platform_id, platform_refs)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'AssetService',
    'AssetExistsError',
    'AssetNotFoundError',
    'AssetStateError',
]
