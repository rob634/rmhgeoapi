# ============================================================================
# CLAUDE CONTEXT - ASSET SERVICE (ASSET/RELEASE LIFECYCLE)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Service - V0.9 Asset/Release lifecycle orchestration
# PURPOSE: Coordinate Asset (identity) and Release (versioned artifact) lifecycle
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: AssetService, ReleaseExistsError, ReleaseNotFoundError, ReleaseStateError
# DEPENDENCIES: infrastructure.asset_repository, infrastructure.release_repository
# ============================================================================
"""
Asset Service -- Asset/Release Lifecycle Orchestration.

Part of the V0.9 Asset/Release entity split. Replaces the V0.8 AssetService
which operated on the monolithic GeospatialAsset. This service coordinates
the two-entity design:

    - Asset: Stable identity container (find or create)
    - Release: Versioned artifact with processing + approval lifecycle

Key Flows:
    - Submit: find_or_create_asset() -> get_or_overwrite_release()
    - Overwrite: find_or_create_asset() -> get_or_overwrite_release(overwrite=True)
    - Approval: handled by AssetApprovalService.approve_release() (atomic)
    - Status: get_release(), get_latest_release(), get_version_history()

Exports:
    AssetService: Lifecycle orchestration for Asset + Release
    ReleaseExistsError: Raised when draft exists and overwrite=False
    ReleaseNotFoundError: Raised when release not found
    ReleaseStateError: Raised when release is in invalid state for operation

Created: 21 FEB 2026 as part of V0.9 Asset/Release entity split
"""

import hashlib
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from uuid import uuid4

from util_logger import LoggerFactory, ComponentType
from core.models.asset import (
    Asset,
    AssetRelease,
    ApprovalState,
    ClearanceState,
    ProcessingStatus
)

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "AssetService")


# ============================================================================
# EXCEPTIONS
# ============================================================================

class ReleaseExistsError(Exception):
    """Raised when a draft release exists and overwrite=False."""
    def __init__(self, asset_id: str, release_id: str):
        self.asset_id = asset_id
        self.release_id = release_id
        super().__init__(
            f"Draft release exists for asset {asset_id}: {release_id}. "
            f"Use overwrite=True to replace."
        )


class ReleaseNotFoundError(Exception):
    """Raised when release not found for operation."""
    def __init__(self, identifier: str, identifier_type: str = "release_id"):
        self.identifier = identifier
        self.identifier_type = identifier_type
        super().__init__(f"Release not found: {identifier_type}={identifier}")


class ReleaseStateError(Exception):
    """Raised when release is in invalid state for requested operation."""
    def __init__(self, release_id: str, current_state: str, required_state: str, operation: str):
        self.release_id = release_id
        super().__init__(
            f"Cannot {operation} release {release_id}: "
            f"current state is '{current_state}', requires '{required_state}'"
        )


# ============================================================================
# SERVICE
# ============================================================================

class AssetService:
    """
    V0.9 Asset/Release lifecycle orchestration.

    Coordinates:
    - Asset: Stable identity container (find or create)
    - Release: Versioned artifact with processing + approval lifecycle

    Key flows:
    - Submit: find_or_create_asset() -> get_or_overwrite_release()
    - Overwrite: find_or_create_asset() -> get_or_overwrite_release()
    - Approval: handled by AssetApprovalService.approve_release() (atomic)
    - Status: get_release(), get_latest_release(), get_version_history()
    """

    def __init__(self):
        """Initialize with repository dependencies (lazy imports)."""
        from infrastructure.asset_repository import AssetRepository
        from infrastructure.release_repository import ReleaseRepository
        self.asset_repo = AssetRepository()
        self.release_repo = ReleaseRepository()

    # =========================================================================
    # ASSET LIFECYCLE
    # =========================================================================

    def find_or_create_asset(
        self,
        platform_id: str,
        dataset_id: str,
        resource_id: str,
        data_type: str
    ) -> Tuple[Asset, str]:
        """
        Find an existing active asset or create a new one.

        Delegates to AssetRepository.find_or_create() which uses advisory
        locks for concurrent serialization.

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            dataset_id: Dataset identifier (e.g., "floods")
            resource_id: Resource identifier (e.g., "jakarta")
            data_type: "raster" or "vector"

        Returns:
            Tuple of (Asset, operation) where operation is "existing" or "created"
        """
        asset, operation = self.asset_repo.find_or_create(
            platform_id=platform_id,
            dataset_id=dataset_id,
            resource_id=resource_id,
            data_type=data_type
        )
        logger.info(
            f"find_or_create_asset: {operation} asset {asset.asset_id[:16]}... "
            f"(platform={platform_id}, dataset={dataset_id}, resource={resource_id})"
        )
        return asset, operation

    # =========================================================================
    # RELEASE LIFECYCLE
    # =========================================================================

    def create_release(
        self,
        asset_id: str,
        stac_item_id: str,
        stac_collection_id: str,
        blob_path: Optional[str] = None,
        job_id: Optional[str] = None,
        request_id: Optional[str] = None,
        suggested_version_id: Optional[str] = None,
        data_type: Optional[str] = None,
        version_ordinal: int = 1
    ) -> AssetRelease:
        """
        Create a new draft release under an asset.

        Generates a deterministic release_id from asset_id + request_id/job_id
        + release_count. The release_count disambiguates successive drafts
        after prior releases are approved (prevents PK collision).
        The release starts as a draft (version_id=None) with
        approval_state=PENDING_REVIEW and processing_status=PENDING.
        version_ordinal is set at creation (reserved slot), not at approval.

        Note: table_name removed (26 FEB 2026) — now in app.release_tables.

        Args:
            asset_id: Parent asset identifier
            stac_item_id: STAC item identifier
            stac_collection_id: STAC collection identifier
            blob_path: Azure Blob path for raster outputs
            job_id: Processing job identifier
            request_id: API request identifier for audit trail
            suggested_version_id: Submitter's suggested version (metadata only)
            data_type: Data type hint (informational, not stored on release)

        Returns:
            Created AssetRelease (draft)
        """
        # Generate deterministic release_id
        # Include release_count so successive drafts (after approval) get unique IDs.
        # Same inputs within a release cycle → same hash → idempotent.
        # After approval increments release_count → different hash → no PK collision.
        uniquifier = request_id or job_id or str(uuid4())
        asset = self.asset_repo.get_by_id(asset_id)
        release_count = asset.release_count if asset else 0
        release_id = hashlib.sha256(
            f"{asset_id}|{uniquifier}|{release_count}".encode()
        ).hexdigest()[:32]

        # Vector data does not go in STAC (01 MAR 2026 design decision)
        # Vector discovery is via PostGIS/OGC Features API.
        if data_type == 'vector' or (asset and asset.data_type == 'vector'):
            stac_item_id = None
            stac_collection_id = None

        release = AssetRelease(
            release_id=release_id,
            asset_id=asset_id,
            # Version: None = draft (assigned at approval), ordinal reserved at creation
            version_id=None,
            suggested_version_id=suggested_version_id,
            version_ordinal=version_ordinal,
            revision=1,
            # Flags
            is_served=False,
            request_id=request_id,
            # Physical outputs (table_name removed → app.release_tables)
            blob_path=blob_path,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            # Processing lifecycle
            job_id=job_id,
            processing_status=ProcessingStatus.PENDING,
            # Approval lifecycle
            approval_state=ApprovalState.PENDING_REVIEW,
            clearance_state=ClearanceState.UNCLEARED,
        )

        created = self.release_repo.create_and_count_atomic(release)

        logger.info(
            f"Created draft release {release_id[:16]}... for asset {asset_id[:16]}... "
            f"(stac_item={stac_item_id}, job={job_id})"
        )
        return created

    def get_or_overwrite_release(
        self,
        asset_id: str,
        overwrite: bool,
        stac_item_id: str,
        stac_collection_id: str,
        blob_path: Optional[str] = None,
        job_id: Optional[str] = None,
        request_id: Optional[str] = None,
        suggested_version_id: Optional[str] = None,
        data_type: Optional[str] = None
    ) -> Tuple[AssetRelease, str]:
        """
        Core submit flow with decision matrix (04 APR 2026).

        Decision matrix (given existing release state vs caller intent):
        - No prior release          → create first release
        - overwrite + not approved  → reprocess same slot (revision++)
        - overwrite + approved      → REJECT (revoke first)
        - new version_id + terminal → create new ordinal
        - new version_id + active   → REJECT (resolve current first)
        - no flags + release exists → return "existing" (submit.py returns 409)

        Args:
            asset_id: Parent asset identifier
            overwrite: If True, allow overwriting existing release
            stac_item_id: STAC item identifier
            stac_collection_id: STAC collection identifier
            blob_path: Azure Blob path for raster outputs
            job_id: Processing job identifier
            request_id: API request identifier
            suggested_version_id: Submitter's suggested version (metadata only)
            data_type: Data type hint (informational)

        Returns:
            Tuple of (AssetRelease, operation) where operation is:
            - "created": First release created for this asset
            - "existing": Release exists, no overwrite/advance (caller should 409)
            - "overwritten": Existing release overwritten (revision incremented)
            - "new_version": New version release created (next ordinal)

        Raises:
            ReleaseStateError: If overwrite of approved, or version advance
                               over in-progress work
        """
        # -----------------------------------------------------------------
        # Step 1: Find current release for this asset (any state)
        # -----------------------------------------------------------------
        current = self.release_repo.get_current_release(asset_id)

        # -----------------------------------------------------------------
        # CASE A: No prior release — first submission
        # -----------------------------------------------------------------
        if current is None:
            logger.info(f"Creating first release for asset {asset_id[:16]}...")
            release = self.create_release(
                asset_id=asset_id,
                stac_item_id=stac_item_id,
                stac_collection_id=stac_collection_id,
                blob_path=blob_path,
                job_id=job_id,
                request_id=request_id,
                suggested_version_id=suggested_version_id,
                data_type=data_type,
                version_ordinal=1,
            )
            return release, "created"

        # -----------------------------------------------------------------
        # Determine caller intent
        # -----------------------------------------------------------------
        is_approved = current.approval_state == ApprovalState.APPROVED
        is_terminal = current.approval_state in (
            ApprovalState.APPROVED, ApprovalState.REVOKED
        )
        is_version_advance = (
            suggested_version_id
            and current.suggested_version_id
            and suggested_version_id != current.suggested_version_id
        )

        # -----------------------------------------------------------------
        # CASE B: Overwrite requested
        # -----------------------------------------------------------------
        if overwrite:
            if is_approved:
                raise ReleaseStateError(
                    current.release_id,
                    "approved",
                    "pending_review, rejected, failed, or revoked",
                    "overwrite. Revoke first via POST /api/platform/revoke, "
                    "then resubmit with overwrite: true"
                )
            if not current.can_overwrite():
                state = f"{current.approval_state.value}/processing={current.processing_status.value}"
                raise ReleaseStateError(
                    current.release_id,
                    state,
                    "pending_review, rejected, or revoked (and not actively processing)",
                    "overwrite"
                )
            # Clean stale PostGIS table mappings before reprocessing
            from infrastructure.release_table_repository import ReleaseTableRepository
            ReleaseTableRepository().delete_for_release(current.release_id)

            self.release_repo.update_overwrite(
                current.release_id,
                revision=current.revision + 1,
            )
            updated = self.release_repo.get_by_id(current.release_id)
            logger.info(
                f"Overwritten release {current.release_id[:16]}... "
                f"(revision {updated.revision})"
            )
            return updated, "overwritten"

        # -----------------------------------------------------------------
        # CASE C: Version advance (new version_id, no overwrite)
        # -----------------------------------------------------------------
        if is_version_advance:
            if not is_terminal:
                raise ReleaseStateError(
                    current.release_id,
                    current.approval_state.value,
                    "approved or revoked",
                    f"advance version to '{suggested_version_id}'. "
                    f"Current version '{current.suggested_version_id}' is in state "
                    f"'{current.approval_state.value}'. Approve, reject, or "
                    f"overwrite the current release first"
                )
            next_ordinal = self.release_repo.get_next_version_ordinal(asset_id)
            logger.info(
                f"Version advance for asset {asset_id[:16]}... "
                f"('{current.suggested_version_id}' -> '{suggested_version_id}', "
                f"next ordinal: {next_ordinal})"
            )
            release = self.create_release(
                asset_id=asset_id,
                stac_item_id=stac_item_id,
                stac_collection_id=stac_collection_id,
                blob_path=blob_path,
                job_id=job_id,
                request_id=request_id,
                suggested_version_id=suggested_version_id,
                data_type=data_type,
                version_ordinal=next_ordinal,
            )
            return release, "new_version"

        # -----------------------------------------------------------------
        # CASE D: No flags, release exists — reject (submit.py returns 409)
        # -----------------------------------------------------------------
        logger.info(
            f"Existing release found for asset {asset_id[:16]}... "
            f"(state={current.approval_state.value}, no overwrite/advance)"
        )
        return current, "existing"

    # =========================================================================
    # READ -- ASSET
    # =========================================================================

    def get_active_asset(self, asset_id: str) -> Optional[Asset]:
        """
        Get an asset by ID, only if active (not soft-deleted).

        Args:
            asset_id: Asset identifier

        Returns:
            Asset if found and active, None otherwise
        """
        asset = self.asset_repo.get_by_id(asset_id)
        if asset and asset.is_active():
            return asset
        return None

    def get_asset_by_identity(
        self,
        platform_id: str,
        dataset_id: str,
        resource_id: str
    ) -> Optional[Asset]:
        """
        Get an active asset by its identity triple.

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            dataset_id: Dataset identifier
            resource_id: Resource identifier

        Returns:
            Asset if found and active, None otherwise
        """
        return self.asset_repo.get_by_identity(
            platform_id=platform_id,
            dataset_id=dataset_id,
            resource_id=resource_id
        )

    # =========================================================================
    # READ -- RELEASE
    # =========================================================================

    def get_release(self, release_id: str) -> Optional[AssetRelease]:
        """
        Get a release by its primary key.

        Args:
            release_id: Release identifier

        Returns:
            AssetRelease if found, None otherwise
        """
        return self.release_repo.get_by_id(release_id)

    def get_latest_release(self, asset_id: str) -> Optional[AssetRelease]:
        """
        Get the latest approved release for an asset.

        Computed: highest version_ordinal among approved releases.

        Args:
            asset_id: Parent asset identifier

        Returns:
            AssetRelease if found, None otherwise
        """
        return self.release_repo.get_latest(asset_id)

    def get_version_history(self, asset_id: str) -> List[AssetRelease]:
        """
        Get all releases for an asset, ordered by version.

        Drafts (version_ordinal IS NULL) sort last, then by created_at DESC.

        Args:
            asset_id: Parent asset identifier

        Returns:
            List of AssetRelease models
        """
        return self.release_repo.list_by_asset(asset_id)

    def get_release_by_version(
        self,
        asset_id: str,
        version_id: str
    ) -> Optional[AssetRelease]:
        """
        Get a specific versioned release.

        Args:
            asset_id: Parent asset identifier
            version_id: Version identifier (e.g., "v1", "v2")

        Returns:
            AssetRelease if found, None otherwise
        """
        return self.release_repo.get_by_version(asset_id, version_id)

    def get_release_by_job_id(self, job_id: str) -> Optional[AssetRelease]:
        """
        Find a release by its processing job ID.

        Args:
            job_id: Job identifier

        Returns:
            AssetRelease if found, None otherwise
        """
        return self.release_repo.get_by_job_id(job_id)

    # =========================================================================
    # UPDATE -- PROCESSING
    # =========================================================================

    def cleanup_orphaned_release(self, release_id: str, asset_id: str) -> bool:
        """
        Delete an orphaned release and decrement asset release_count.

        Used as a compensating action when job creation fails after release
        creation, or to auto-clean orphans detected on re-submission.

        Args:
            release_id: Orphaned release to delete
            asset_id: Parent asset whose release_count to decrement

        Returns:
            True if release was deleted, False if not found
        """
        return self.release_repo.delete_and_uncount_atomic(release_id, asset_id)

    def link_job_to_release(self, release_id: str, job_id: str) -> bool:
        """
        Link a processing job to a release.

        Sets the job_id on the release and resets processing_status to PENDING.

        Args:
            release_id: Release to link
            job_id: Job identifier

        Returns:
            True if updated, False if release not found
        """
        return self.release_repo.link_job(release_id, job_id)

    def update_processing_status(
        self,
        release_id: str,
        status: ProcessingStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error: Optional[str] = None
    ) -> bool:
        """
        Update processing lifecycle status on a release.

        Args:
            release_id: Release to update
            status: New processing status
            started_at: When processing started (preserved if None)
            completed_at: When processing completed
            error: Error message if failed

        Returns:
            True if updated, False if release not found
        """
        return self.release_repo.update_processing_status(
            release_id=release_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            error=error
        )

    # =========================================================================
    # UPDATE -- STAC + PHYSICAL OUTPUTS
    # =========================================================================

    def update_stac_cache(
        self,
        release_id: str,
        stac_item_json: Dict[str, Any]
    ) -> bool:
        """
        Cache STAC item JSON for materialization to pgSTAC.

        Args:
            release_id: Release to update
            stac_item_json: STAC item dict to cache

        Returns:
            True if updated, False if release not found
        """
        return self.release_repo.update_stac_item_json(release_id, stac_item_json)

    def update_physical_outputs(
        self,
        release_id: str,
        blob_path: Optional[str] = None,
        stac_item_id: Optional[str] = None,
        content_hash: Optional[str] = None,
        source_file_hash: Optional[str] = None,
        output_file_hash: Optional[str] = None
    ) -> bool:
        """
        Update physical output fields on a release.

        Only provided fields are updated (dynamic SET clause).
        Note: table_name removed (26 FEB 2026) — now in app.release_tables.

        Args:
            release_id: Release to update
            blob_path: Azure Blob Storage path for raster outputs
            stac_item_id: STAC item identifier
            content_hash: Hash of processed output content
            source_file_hash: Hash of original source file
            output_file_hash: Hash of final output file

        Returns:
            True if updated, False if release not found or no fields provided
        """
        return self.release_repo.update_physical_outputs(
            release_id=release_id,
            blob_path=blob_path,
            stac_item_id=stac_item_id,
            content_hash=content_hash,
            source_file_hash=source_file_hash,
            output_file_hash=output_file_hash
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'AssetService',
    'ReleaseExistsError',
    'ReleaseNotFoundError',
    'ReleaseStateError',
]
