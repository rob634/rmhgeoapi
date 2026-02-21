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
    - Approval: assign_version() (called by AssetApprovalService)
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
    - Approval: assign_version() (called by AssetApprovalService)
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
        table_name: Optional[str] = None,
        job_id: Optional[str] = None,
        request_id: Optional[str] = None,
        suggested_version_id: Optional[str] = None,
        data_type: Optional[str] = None
    ) -> AssetRelease:
        """
        Create a new draft release under an asset.

        Generates a deterministic release_id from asset_id + request_id/job_id.
        The release starts as a draft (version_id=None) with
        approval_state=PENDING_REVIEW and processing_status=PENDING.

        Args:
            asset_id: Parent asset identifier
            stac_item_id: STAC item identifier
            stac_collection_id: STAC collection identifier
            blob_path: Azure Blob path for raster outputs
            table_name: PostGIS table name for vector outputs
            job_id: Processing job identifier
            request_id: API request identifier for audit trail
            suggested_version_id: Submitter's suggested version (metadata only)
            data_type: Data type hint (informational, not stored on release)

        Returns:
            Created AssetRelease (draft)
        """
        # Generate deterministic release_id
        uniquifier = request_id or job_id or str(uuid4())
        release_id = hashlib.sha256(
            f"{asset_id}|{uniquifier}".encode()
        ).hexdigest()[:32]

        release = AssetRelease(
            release_id=release_id,
            asset_id=asset_id,
            # Version: None = draft (assigned at approval)
            version_id=None,
            suggested_version_id=suggested_version_id,
            version_ordinal=None,
            revision=1,
            # Flags
            is_latest=False,
            is_served=True,
            request_id=request_id,
            # Physical outputs
            blob_path=blob_path,
            table_name=table_name,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            # Processing lifecycle
            job_id=job_id,
            processing_status=ProcessingStatus.PENDING,
            # Approval lifecycle
            approval_state=ApprovalState.PENDING_REVIEW,
            clearance_state=ClearanceState.UNCLEARED,
        )

        created = self.release_repo.create(release)
        self.asset_repo.increment_release_count(asset_id)

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
        table_name: Optional[str] = None,
        job_id: Optional[str] = None,
        request_id: Optional[str] = None,
        suggested_version_id: Optional[str] = None,
        data_type: Optional[str] = None
    ) -> Tuple[AssetRelease, str]:
        """
        Core submit flow: get existing draft, overwrite it, or create new.

        Logic:
        1. Check for existing draft release for this asset
        2. If draft exists AND overwrite=True:
           - Validate the draft can be overwritten (PENDING_REVIEW or REJECTED)
           - Increment revision counter and reset processing state
           - Return (updated_release, "overwritten")
        3. If draft exists AND overwrite=False:
           - Return (existing_draft, "existing") -- idempotent
        4. If no draft exists:
           - Create a new release
           - Return (new_release, "created")

        Args:
            asset_id: Parent asset identifier
            overwrite: If True, allow overwriting existing draft
            stac_item_id: STAC item identifier
            stac_collection_id: STAC collection identifier
            blob_path: Azure Blob path for raster outputs
            table_name: PostGIS table name for vector outputs
            job_id: Processing job identifier
            request_id: API request identifier
            suggested_version_id: Submitter's suggested version (metadata only)
            data_type: Data type hint (informational)

        Returns:
            Tuple of (AssetRelease, operation) where operation is:
            - "created": New release created
            - "existing": Existing draft returned (idempotent, no overwrite)
            - "overwritten": Existing draft overwritten

        Raises:
            ReleaseStateError: If overwrite requested but draft is in
                               non-overwritable state (APPROVED or REVOKED)
        """
        existing_draft = self.release_repo.get_draft(asset_id)

        if existing_draft:
            if overwrite:
                if not existing_draft.can_overwrite():
                    raise ReleaseStateError(
                        existing_draft.release_id,
                        existing_draft.approval_state.value,
                        "pending_review or rejected",
                        "overwrite"
                    )
                self.release_repo.update_overwrite(
                    existing_draft.release_id,
                    revision=existing_draft.revision + 1,
                )
                updated = self.release_repo.get_by_id(existing_draft.release_id)
                logger.info(
                    f"Overwritten release {existing_draft.release_id[:16]}... "
                    f"(revision {updated.revision})"
                )
                return updated, "overwritten"
            else:
                # Draft exists, no overwrite flag -- return existing (idempotent)
                logger.info(
                    f"Existing draft found: {existing_draft.release_id[:16]}..."
                )
                return existing_draft, "existing"

        # No draft -- create new release
        release = self.create_release(
            asset_id=asset_id,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            blob_path=blob_path,
            table_name=table_name,
            job_id=job_id,
            request_id=request_id,
            suggested_version_id=suggested_version_id,
        )
        return release, "created"

    # =========================================================================
    # VERSION ASSIGNMENT (called by AssetApprovalService)
    # =========================================================================

    def assign_version(
        self,
        release_id: str,
        version_id: str,
        reviewer: str
    ) -> AssetRelease:
        """
        Assign an official version to a draft release at approval time.

        Called by AssetApprovalService when approving a release. This:
        1. Validates the release exists and is a draft (version_id is None)
        2. Computes version_ordinal from existing versioned releases
        3. Flips is_latest atomically
        4. Updates version fields on the release

        Args:
            release_id: Release to assign version to
            version_id: Version identifier (e.g., "v1", "v2")
            reviewer: Who is assigning the version (audit trail)

        Returns:
            Updated AssetRelease with version assigned

        Raises:
            ReleaseNotFoundError: If release not found
            ReleaseStateError: If release already has a version (not a draft)
        """
        release = self.release_repo.get_by_id(release_id)
        if not release:
            raise ReleaseNotFoundError(release_id)

        if release.version_id is not None:
            raise ReleaseStateError(
                release_id,
                f"versioned ({release.version_id})",
                "draft (version_id=None)",
                "assign_version"
            )

        # Compute version_ordinal: count existing versioned releases + 1
        existing_releases = self.release_repo.list_by_asset(release.asset_id)
        versioned_count = sum(
            1 for r in existing_releases
            if r.version_id is not None and r.release_id != release_id
        )
        version_ordinal = versioned_count + 1

        # Flip is_latest atomically: clear all, then set this one
        self.release_repo.flip_is_latest(release.asset_id, release_id)

        # Assign version fields
        self.release_repo.update_version_assignment(
            release_id=release_id,
            version_id=version_id,
            version_ordinal=version_ordinal,
            is_latest=True
        )

        # Re-fetch and return
        updated = self.release_repo.get_by_id(release_id)
        logger.info(
            f"assign_version: {release_id[:16]}... -> version_id={version_id}, "
            f"ordinal={version_ordinal}, reviewer={reviewer}"
        )
        return updated

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

        Uses the is_latest=true + approval_state='approved' filter.

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
        table_name: Optional[str] = None,
        stac_item_id: Optional[str] = None,
        content_hash: Optional[str] = None,
        source_file_hash: Optional[str] = None,
        output_file_hash: Optional[str] = None
    ) -> bool:
        """
        Update physical output fields on a release.

        Only provided fields are updated (dynamic SET clause).

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
        return self.release_repo.update_physical_outputs(
            release_id=release_id,
            blob_path=blob_path,
            table_name=table_name,
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
