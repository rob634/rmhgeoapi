# ============================================================================
# CLAUDE CONTEXT - ASSET APPROVAL SERVICE (RELEASE-BASED APPROVAL)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Service - V0.9 approval workflow operates on Release, not Asset
# PURPOSE: Manage approval state transitions on AssetRelease
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: AssetApprovalService
# DEPENDENCIES: infrastructure.release_repository, services.asset_service
# ============================================================================
"""
Asset Approval Service -- Release-Based Approval Workflow.

Part of the V0.9 Asset/Release entity split. Approval now targets a release_id,
not an asset_id. The Asset entity is NEVER mutated during approval.

Design Principle:
    AssetRelease is the approval target. All approval state lives on the release.
    The Asset (identity container) remains untouched.

Workflow:
    1. Platform submit creates Release with approval_state=PENDING_REVIEW
    2. Processing completes, STAC dict cached on Release.stac_item_json
    3. Reviewer approves/rejects via this service
    4. At approval: version assigned, STAC materialized to pgSTAC
    5. If PUBLIC: ADF pipeline triggered
    6. If revoked: STAC deleted from pgSTAC, is_latest flipped

State Transitions:
    PENDING_REVIEW -> APPROVED (with clearance_state)
    PENDING_REVIEW -> REJECTED (with rejection_reason)
    APPROVED -> REVOKED (for unpublish, terminal state)
    REJECTED -> PENDING_REVIEW (only via new version submit)

Key V0.9 Change vs V0.8:
    - V0.8: approve_asset(asset_id) mutated GeospatialAsset directly
    - V0.9: approve_release(release_id) updates AssetRelease; Asset untouched
    - STAC materialized from Release.stac_item_json (not cog_metadata)

Exports:
    AssetApprovalService: Approval workflow for AssetRelease
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType
from core.models.asset import (
    AssetRelease,
    ApprovalState,
    ClearanceState,
    ProcessingStatus
)

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "AssetApprovalService")


class AssetApprovalService:
    """
    V0.9 approval workflow operating on AssetRelease.

    Key difference from V0.8: approval targets release_id, not asset_id.
    The Asset entity is never mutated during approval.

    Workflow:
        1. Platform submit creates Release with approval_state=PENDING_REVIEW
        2. Processing completes, STAC dict cached on Release.stac_item_json
        3. Reviewer approves/rejects via this service
        4. At approval: version assigned, STAC materialized to pgSTAC
        5. If PUBLIC: ADF pipeline triggered
        6. If revoked: STAC deleted from pgSTAC, is_latest flipped
    """

    def __init__(self):
        """Initialize with repository and service dependencies (lazy imports)."""
        from infrastructure.release_repository import ReleaseRepository
        from services.asset_service import AssetService
        self.release_repo = ReleaseRepository()
        self.asset_service = AssetService()

    # =========================================================================
    # APPROVE
    # =========================================================================

    def approve_release(
        self,
        release_id: str,
        reviewer: str,
        clearance_state: ClearanceState,
        version_id: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve a release for publication.

        Steps:
        1. Validate release exists and is PENDING_REVIEW
        2. Warn (don't block) if processing_status != COMPLETED
        3. Assign version (version_id, ordinal, is_latest) via asset_service
        4. Update approval_state to APPROVED
        5. Update clearance (with made_public tracking if PUBLIC)
        6. Materialize STAC from cached stac_item_json
        7. Trigger ADF if PUBLIC

        Args:
            release_id: Release to approve
            reviewer: Email or identifier of reviewer
            clearance_state: OUO or PUBLIC (determines post-approval action)
            version_id: Version to assign (e.g., "v1", "v2")
            notes: Optional approval notes

        Returns:
            Dict with:
                success: bool
                release: Updated AssetRelease dict
                action: 'approved_ouo' or 'approved_public_adf_triggered'
                stac_updated: bool
                adf_run_id: str (if PUBLIC)
                error: str (if failed)
        """
        logger.info(
            f"Approving release {release_id[:16]}... by {reviewer} "
            f"(clearance: {clearance_state.value}, version: {version_id})"
        )

        # Get release
        release = self.release_repo.get_by_id(release_id)
        if not release:
            return {
                'success': False,
                'error': f"Release not found: {release_id}"
            }

        # Validate state
        if not release.can_approve():
            return {
                'success': False,
                'error': (
                    f"Cannot approve: approval_state is '{release.approval_state.value}', "
                    f"expected 'pending_review'"
                )
            }

        # Warn if processing is not complete (don't block)
        if release.processing_status != ProcessingStatus.COMPLETED:
            logger.warning(
                f"Approving release with processing_status={release.processing_status.value} "
                f"(expected COMPLETED) - proceeding anyway"
            )

        now = datetime.now(timezone.utc)

        # Use pre-set ordinal from draft creation (reserved slot)
        version_ordinal = release.version_ordinal

        # Atomic approval: flip_is_latest + version assignment + approval
        # state + clearance in a single transaction. All-or-nothing.
        success = self.release_repo.approve_release_atomic(
            release_id=release_id,
            asset_id=release.asset_id,
            version_id=version_id,
            version_ordinal=version_ordinal,
            approval_state=ApprovalState.APPROVED,
            reviewer=reviewer,
            reviewed_at=now,
            clearance_state=clearance_state,
            approval_notes=notes
        )

        if not success:
            return {
                'success': False,
                'error': (
                    "Atomic approval failed: release not found or not in "
                    "pending_review state (concurrent approval?)"
                )
            }

        # Update stac_item_id to final versioned form (draft-N -> version_id)
        from services.platform_translation import generate_stac_item_id
        from infrastructure import AssetRepository
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(release.asset_id)
        if asset:
            final_stac_item_id = generate_stac_item_id(
                asset.dataset_id, asset.resource_id, version_id
            )
            if final_stac_item_id != release.stac_item_id:
                self.release_repo.update_physical_outputs(
                    release_id=release_id,
                    stac_item_id=final_stac_item_id
                )
                logger.info(
                    f"Updated stac_item_id: {release.stac_item_id} -> {final_stac_item_id}"
                )
                release.stac_item_id = final_stac_item_id

        # Materialize STAC item to pgSTAC from cached stac_item_json
        stac_result = self._materialize_stac(release, reviewer, clearance_state)

        # Trigger ADF if PUBLIC
        adf_run_id = None
        action = 'approved_ouo'

        if clearance_state == ClearanceState.PUBLIC:
            adf_result = self._trigger_adf_pipeline(release)
            if adf_result.get('success'):
                adf_run_id = adf_result.get('run_id')
                action = 'approved_public_adf_triggered'
                # Update clearance with ADF run ID
                self.release_repo.update_clearance(
                    release_id=release_id,
                    clearance_state=clearance_state,
                    cleared_by=reviewer,
                    adf_run_id=adf_run_id
                )
                logger.info(f"ADF triggered for {release_id[:16]}...: {adf_run_id}")
            else:
                logger.warning(
                    f"ADF trigger failed for {release_id[:16]}...: {adf_result.get('error')}"
                )
                action = 'approved_public_adf_failed'

        # Get updated release
        updated_release = self.release_repo.get_by_id(release_id)

        logger.info(
            f"Release {release_id[:16]}... approved by {reviewer} "
            f"(clearance: {clearance_state.value}, version: {version_id})"
        )

        response = {
            'success': True,
            'release': updated_release.to_dict() if updated_release else None,
            'action': action,
            'stac_updated': stac_result.get('success', False),
            'adf_run_id': adf_run_id
        }

        # Include mosaic viewer URL for tiled outputs
        if stac_result.get('mosaic_viewer_url'):
            response['mosaic_viewer_url'] = stac_result['mosaic_viewer_url']

        return response

    # =========================================================================
    # REJECT
    # =========================================================================

    def reject_release(
        self,
        release_id: str,
        reviewer: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Reject a release.

        Args:
            release_id: Release to reject
            reviewer: Email or identifier of reviewer
            reason: Rejection reason (required)

        Returns:
            Dict with:
                success: bool
                release: Updated AssetRelease dict
                error: str (if failed)
        """
        logger.info(f"Rejecting release {release_id[:16]}... by {reviewer}")

        if not reason or not reason.strip():
            return {
                'success': False,
                'error': 'Rejection reason is required'
            }

        # Get release
        release = self.release_repo.get_by_id(release_id)
        if not release:
            return {
                'success': False,
                'error': f"Release not found: {release_id}"
            }

        # Validate state
        if not release.can_approve():
            return {
                'success': False,
                'error': (
                    f"Cannot reject: approval_state is '{release.approval_state.value}', "
                    f"expected 'pending_review'"
                )
            }

        now = datetime.now(timezone.utc)

        # Update release with rejection
        success = self.release_repo.update_approval_state(
            release_id=release_id,
            approval_state=ApprovalState.REJECTED,
            reviewer=reviewer,
            reviewed_at=now,
            rejection_reason=reason
        )

        if not success:
            return {
                'success': False,
                'error': "Failed to update release approval state"
            }

        # Get updated release
        updated_release = self.release_repo.get_by_id(release_id)

        logger.info(f"Release {release_id[:16]}... rejected by {reviewer}: {reason[:50]}...")

        return {
            'success': True,
            'release': updated_release.to_dict() if updated_release else None
        }

    # =========================================================================
    # REVOKE
    # =========================================================================

    def revoke_release(
        self,
        release_id: str,
        revoker: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Revoke a previously approved release (unpublish).

        This is a terminal state - to re-publish, submit a new version.
        DB is updated first (source of truth), then STAC item is deleted.

        If the revoked release was is_latest, the next most recent
        approved release is promoted to is_latest.

        Args:
            release_id: Release to revoke
            revoker: Who is revoking (user email or system ID)
            reason: Revocation reason (required for audit trail)

        Returns:
            Dict with:
                success: bool
                release: Updated AssetRelease dict
                stac_updated: bool
                warning: Audit note
                error: str (if failed)
        """
        logger.info(f"Revoking release {release_id[:16]}... by {revoker}")

        if not reason or not reason.strip():
            return {
                'success': False,
                'error': 'Revocation reason is required for audit trail'
            }

        # Get release
        release = self.release_repo.get_by_id(release_id)
        if not release:
            return {
                'success': False,
                'error': f"Release not found: {release_id}"
            }

        # Validate state
        if not release.can_revoke():
            return {
                'success': False,
                'error': (
                    f"Cannot revoke: approval_state is '{release.approval_state.value}', "
                    f"expected 'approved'"
                )
            }

        # Update DB first (source of truth), then delete STAC.
        # If STAC delete fails, release is correctly REVOKED and orphaned
        # STAC item can be cleaned up. Reverse order (STAC first) risks
        # inconsistent state if DB update fails after STAC deletion.
        success = self.release_repo.update_revocation(
            release_id=release_id,
            revoked_by=revoker,
            revocation_reason=reason
        )

        if not success:
            return {
                'success': False,
                'error': "Failed to update release revocation state (may have been revoked concurrently)"
            }

        # Delete STAC item (after DB state is authoritative)
        stac_result = self._delete_stac(release)

        # If revoked release was is_latest, flip to next most recent approved release
        if release.is_latest:
            versions = self.release_repo.list_by_asset(release.asset_id)
            next_latest = None
            for v in reversed(versions):  # list is ordered by ordinal
                if v.release_id != release_id and v.approval_state == ApprovalState.APPROVED:
                    next_latest = v
                    break
            if next_latest:
                # Guard: check if another release already became is_latest
                # (e.g., concurrent approval flipped it while we were revoking)
                current_latest = self.release_repo.get_latest(release.asset_id)
                if current_latest and current_latest.release_id != release_id:
                    logger.info(
                        f"Skipping is_latest flip — {current_latest.release_id[:16]}... "
                        f"already promoted"
                    )
                else:
                    self.release_repo.flip_is_latest(release.asset_id, next_latest.release_id)
                    logger.info(
                        f"Flipped is_latest to {next_latest.release_id[:16]}... "
                        f"({next_latest.version_id})"
                    )
            else:
                logger.info(f"No other approved releases for asset {release.asset_id[:16]}...")

        # Get updated release
        updated_release = self.release_repo.get_by_id(release_id)

        logger.warning(
            f"AUDIT: Release {release_id[:16]}... REVOKED by {revoker}. "
            f"Reason: {reason}. Version: {release.version_id}."
        )

        # Build response warning based on STAC result
        if stac_result.get('success') and stac_result.get('deleted'):
            stac_warning = 'STAC item deleted from pgSTAC.'
        elif not stac_result.get('success'):
            stac_warning = (
                'WARNING: STAC item deletion failed — item may still be visible in catalog. '
                'Manual cleanup required.'
            )
        else:
            stac_warning = 'No STAC item to delete (never materialized).'

        return {
            'success': True,
            'release': updated_release.to_dict() if updated_release else None,
            'stac_updated': stac_result.get('success', False) and stac_result.get('deleted', False),
            'warning': (
                f'Approved release has been revoked. {stac_warning} '
                'To re-publish, submit a new version.'
            )
        }

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def list_pending_review(self, limit: int = 50) -> List[AssetRelease]:
        """
        List releases awaiting approval (completed processing + pending_review).

        Delegates to ReleaseRepository.list_pending_review which filters
        for processing_status=COMPLETED and approval_state=PENDING_REVIEW.

        Args:
            limit: Maximum results

        Returns:
            List of AssetRelease in PENDING_REVIEW state with COMPLETED processing
        """
        return self.release_repo.list_pending_review(limit)

    def get_approval_stats(self) -> Dict[str, int]:
        """
        Get counts of releases by approval_state.

        Returns:
            Dict like {'pending_review': 5, 'approved': 100, 'rejected': 2, 'revoked': 1}
        """
        return self.release_repo.count_by_approval_state()

    # =========================================================================
    # STAC INTEGRATION
    # =========================================================================

    def _materialize_stac(
        self,
        release: AssetRelease,
        reviewer: str,
        clearance_state: ClearanceState
    ) -> Dict[str, Any]:
        """
        Create pgSTAC item from cached STAC dict at approval time.

        Delegates to STACMaterializer which handles:
        - B2C sanitization (strips geoetl:* properties)
        - Union extent computation across all items in collection
        - TiTiler URL injection
        - Both single COG and tiled output modes

        Args:
            release: The approved AssetRelease
            reviewer: Who approved
            clearance_state: OUO or PUBLIC

        Returns:
            Dict with success, pgstac_id, and optional error
        """
        from services.stac_materialization import STACMaterializer
        materializer = STACMaterializer()
        return materializer.materialize_release(release, reviewer, clearance_state)

    def _delete_stac(self, release: AssetRelease) -> Dict[str, Any]:
        """
        Delete pgSTAC item on revocation.

        Delegates to STACMaterializer.dematerialize_item() which handles:
        - Item deletion from pgSTAC
        - Extent recalculation for remaining items
        - Empty collection cleanup

        The cached stac_item_json on the Release is preserved for auditing.

        Args:
            release: The release being revoked

        Returns:
            Dict with success, deleted, and optional error
        """
        if not release.stac_item_id or not release.stac_collection_id:
            return {
                'success': True,
                'deleted': False,
                'reason': 'Release has no STAC item/collection ID (never materialized)'
            }

        try:
            from services.stac_materialization import STACMaterializer
            from infrastructure.pgstac_repository import PgStacRepository
            materializer = STACMaterializer()

            # Tiled output: delete all items for this release's tiles
            if release.output_mode == 'tiled':
                pgstac = PgStacRepository()
                item_ids = pgstac.get_collection_item_ids(release.stac_collection_id)
                for item_id in item_ids:
                    materializer.dematerialize_item(release.stac_collection_id, item_id)
                return {
                    'success': True,
                    'deleted': len(item_ids) > 0,
                    'items_deleted': len(item_ids)
                }

            # Single COG: delete just this release's item
            result = materializer.dematerialize_item(
                release.stac_collection_id, release.stac_item_id
            )
            return {
                'success': result.get('success', False),
                'deleted': result.get('deleted', False),
            }

        except Exception as e:
            logger.warning(f"Failed to delete STAC item on revocation: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # ADF INTEGRATION
    # =========================================================================

    def _trigger_adf_pipeline(self, release: AssetRelease) -> Dict[str, Any]:
        """
        Trigger ADF pipeline for PUBLIC data export.

        Args:
            release: The approved release

        Returns:
            Dict with success, run_id, and optional error
        """
        try:
            from infrastructure.data_factory import get_data_factory_repository

            adf_repo = get_data_factory_repository()
            if not adf_repo:
                return {
                    'success': False,
                    'error': 'ADF not configured (missing ADF_SUBSCRIPTION_ID or ADF_FACTORY_NAME)'
                }

            result = adf_repo.trigger_pipeline(
                pipeline_name='export_to_public',
                parameters={
                    'release_id': release.release_id,
                    'asset_id': release.asset_id,
                    'stac_item_id': release.stac_item_id,
                    'stac_collection_id': release.stac_collection_id,
                    'data_type': 'raster' if release.blob_path else 'vector',
                    'table_name': release.table_name,
                    'blob_path': release.blob_path
                }
            )

            if result.get('run_id'):
                return {
                    'success': True,
                    'run_id': result['run_id'],
                    'poll_url': result.get('poll_url')
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Unknown ADF error')
                }

        except ImportError:
            return {
                'success': False,
                'error': 'ADF module not available'
            }
        except Exception as e:
            logger.error(f"Error triggering ADF pipeline: {e}")
            return {
                'success': False,
                'error': str(e)
            }


# Module exports
__all__ = ['AssetApprovalService']
