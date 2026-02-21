# ============================================================================
# ASSET APPROVAL SERVICE
# ============================================================================
# STATUS: Service - Approval workflow for GeospatialAsset (Aggregate Root)
# PURPOSE: Manage approval state transitions on GeospatialAsset directly
# CREATED: 08 FEB 2026 (V0.8.11 - Approval Consolidation Phase 2)
# UPDATED: 19 FEB 2026 - STAC as B2C materialized view (materialize at approve, delete at revoke)
# EXPORTS: AssetApprovalService
# DEPENDENCIES: infrastructure.asset_repository, infrastructure.pgstac_repository
# ============================================================================
"""
Asset Approval Service.

Business logic for the approval workflow operating directly on GeospatialAsset.
This replaces the legacy ApprovalService that used a separate DatasetApproval table.

Design Principle:
    GeospatialAsset is the Aggregate Root - all approval state lives on the asset itself.
    No separate approval records needed.

Workflow:
    1. Platform submit creates asset with approval_state=PENDING_REVIEW
    2. Job completes, asset.processing_status=COMPLETED, STAC dict cached in cog_metadata
    3. Reviewer approves/rejects via this service
    4. If approved, STAC item materialized to pgSTAC from cached dict
    5. If PUBLIC, ADF pipeline triggered
    6. If revoked, STAC item deleted from pgSTAC (invisible to consumers)

State Transitions:
    PENDING_REVIEW → APPROVED (with clearance_state)
    PENDING_REVIEW → REJECTED (with rejection_reason)
    APPROVED → REVOKED (for unpublish, terminal state)
    REJECTED → PENDING_REVIEW (only via new version submit)

Exports:
    AssetApprovalService: Approval workflow for GeospatialAsset
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType
from core.models.asset import (
    GeospatialAsset,
    ApprovalState,
    ClearanceState,
    ProcessingStatus
)

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "AssetApprovalService")


class AssetApprovalService:
    """
    Approval workflow service operating on GeospatialAsset (Aggregate Root).

    All approval state is stored directly on GeospatialAsset:
    - approval_state: ApprovalState enum
    - reviewer: who approved/rejected
    - reviewed_at: when
    - rejection_reason: why (if rejected)
    - approval_notes: optional notes
    - revoked_at/by/reason: if revoked

    This service orchestrates:
    - State transitions with validation
    - STAC property updates (app:published, etc.)
    - ADF triggers for PUBLIC clearance
    """

    def __init__(self):
        """Initialize with repository dependencies."""
        from infrastructure.asset_repository import GeospatialAssetRepository
        self.asset_repo = GeospatialAssetRepository()

    # =========================================================================
    # APPROVE
    # =========================================================================

    def approve_asset(
        self,
        asset_id: str,
        reviewer: str,
        clearance_state: ClearanceState,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve an asset for publication.

        Performs the following:
        1. Validates asset exists and is PENDING_REVIEW
        2. Updates GeospatialAsset with approval fields
        3. Updates STAC item with app:published=true
        4. If PUBLIC clearance, triggers ADF pipeline

        Args:
            asset_id: Asset to approve
            reviewer: Email or identifier of reviewer
            clearance_state: OUO or PUBLIC (determines post-approval action)
            notes: Optional approval notes

        Returns:
            Dict with:
                success: bool
                asset: Updated GeospatialAsset dict
                action: 'approved_ouo' or 'approved_public_adf_triggered'
                stac_updated: bool
                adf_run_id: str (if PUBLIC)
                error: str (if failed)
        """
        logger.info(f"Approving asset {asset_id[:16]}... by {reviewer} (clearance: {clearance_state.value})")

        # Get asset
        asset = self.asset_repo.get_by_id(asset_id)
        if not asset:
            return {
                'success': False,
                'error': f"Asset not found: {asset_id}"
            }

        # Validate state
        if not asset.can_approve():
            return {
                'success': False,
                'error': f"Cannot approve: approval_state is '{asset.approval_state}', expected 'pending_review'"
            }

        # Validate processing is complete (should be COMPLETED before approval)
        if asset.processing_status != ProcessingStatus.COMPLETED:
            logger.warning(
                f"Approving asset with processing_status={asset.processing_status.value} "
                f"(expected COMPLETED) - proceeding anyway"
            )

        now = datetime.now(timezone.utc)

        # Update asset with approval
        success = self.asset_repo.update_approval_state(
            asset_id=asset_id,
            approval_state=ApprovalState.APPROVED,
            reviewer=reviewer,
            reviewed_at=now,
            approval_notes=notes,
            clearance_state=clearance_state,
            cleared_at=now,
            cleared_by=reviewer,
            made_public_at=now if clearance_state == ClearanceState.PUBLIC else None,
            made_public_by=reviewer if clearance_state == ClearanceState.PUBLIC else None
        )

        if not success:
            return {
                'success': False,
                'error': f"Failed to update asset approval state"
            }

        # Materialize STAC item to pgSTAC (19 FEB 2026: B2C materialized view)
        stac_result = self._materialize_stac(asset, reviewer, clearance_state)

        # Trigger ADF if PUBLIC
        adf_run_id = None
        action = 'approved_ouo'

        if clearance_state == ClearanceState.PUBLIC:
            adf_result = self._trigger_adf_pipeline(asset)
            if adf_result.get('success'):
                adf_run_id = adf_result.get('run_id')
                action = 'approved_public_adf_triggered'
                # Update asset with ADF run ID
                self.asset_repo.update_adf_run_id(asset_id, adf_run_id)
                logger.info(f"ADF triggered for {asset_id[:16]}...: {adf_run_id}")
            else:
                logger.warning(f"ADF trigger failed for {asset_id[:16]}...: {adf_result.get('error')}")
                action = 'approved_public_adf_failed'

        # Get updated asset
        updated_asset = self.asset_repo.get_by_id(asset_id)

        logger.info(f"Asset {asset_id[:16]}... approved by {reviewer} (clearance: {clearance_state.value})")

        return {
            'success': True,
            'asset': updated_asset.to_dict() if updated_asset else None,
            'action': action,
            'stac_updated': stac_result.get('success', False),
            'adf_run_id': adf_run_id
        }

    # =========================================================================
    # REJECT
    # =========================================================================

    def reject_asset(
        self,
        asset_id: str,
        reviewer: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Reject an asset.

        Args:
            asset_id: Asset to reject
            reviewer: Email or identifier of reviewer
            reason: Rejection reason (required)

        Returns:
            Dict with:
                success: bool
                asset: Updated GeospatialAsset dict
                error: str (if failed)
        """
        logger.info(f"Rejecting asset {asset_id[:16]}... by {reviewer}")

        if not reason or not reason.strip():
            return {
                'success': False,
                'error': 'Rejection reason is required'
            }

        # Get asset
        asset = self.asset_repo.get_by_id(asset_id)
        if not asset:
            return {
                'success': False,
                'error': f"Asset not found: {asset_id}"
            }

        # Validate state
        if not asset.can_reject():
            return {
                'success': False,
                'error': f"Cannot reject: approval_state is '{asset.approval_state}', expected 'pending_review'"
            }

        now = datetime.now(timezone.utc)

        # Update asset with rejection
        success = self.asset_repo.update_approval_state(
            asset_id=asset_id,
            approval_state=ApprovalState.REJECTED,
            reviewer=reviewer,
            reviewed_at=now,
            rejection_reason=reason
        )

        if not success:
            return {
                'success': False,
                'error': f"Failed to update asset approval state"
            }

        # Get updated asset
        updated_asset = self.asset_repo.get_by_id(asset_id)

        logger.info(f"Asset {asset_id[:16]}... rejected by {reviewer}: {reason[:50]}...")

        return {
            'success': True,
            'asset': updated_asset.to_dict() if updated_asset else None
        }

    # =========================================================================
    # REVOKE
    # =========================================================================

    def revoke_asset(
        self,
        asset_id: str,
        revoker: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Revoke a previously approved asset (unpublish).

        This is a terminal state - to re-publish, submit a new version.

        Args:
            asset_id: Asset to revoke
            revoker: Who is revoking (user email or system ID like "unpublish_job:xxx")
            reason: Revocation reason (required for audit trail)

        Returns:
            Dict with:
                success: bool
                asset: Updated GeospatialAsset dict
                stac_updated: bool
                warning: Audit note
                error: str (if failed)
        """
        logger.info(f"Revoking asset {asset_id[:16]}... by {revoker}")

        if not reason or not reason.strip():
            return {
                'success': False,
                'error': 'Revocation reason is required for audit trail'
            }

        # Get asset
        asset = self.asset_repo.get_by_id(asset_id)
        if not asset:
            return {
                'success': False,
                'error': f"Asset not found: {asset_id}"
            }

        # Validate state
        if not asset.can_revoke():
            return {
                'success': False,
                'error': f"Cannot revoke: approval_state is '{asset.approval_state}', expected 'approved'"
            }

        now = datetime.now(timezone.utc)

        # Update asset with revocation
        success = self.asset_repo.update_revocation(
            asset_id=asset_id,
            revoked_at=now,
            revoked_by=revoker,
            revocation_reason=reason
        )

        if not success:
            return {
                'success': False,
                'error': f"Failed to update asset revocation state"
            }

        # Delete STAC item (19 FEB 2026: approved=visible, not approved=invisible)
        stac_result = self._delete_stac(asset)

        # Get updated asset
        updated_asset = self.asset_repo.get_by_id(asset_id)

        # 19 FEB 2026: Version info cleared on revoke — asset returns to draft state
        logger.warning(
            f"AUDIT: Asset {asset_id[:16]}... REVOKED by {revoker}. Reason: {reason}. "
            f"Version info cleared (lineage_id, version_ordinal, version_id) — asset is now draft."
        )

        return {
            'success': True,
            'asset': updated_asset.to_dict() if updated_asset else None,
            'stac_updated': stac_result.get('success', False),
            'warning': 'Approved asset has been revoked and version info cleared. Re-approval will require version assignment.'
        }

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def list_pending_review(
        self,
        limit: int = 50,
        include_processing_incomplete: bool = False
    ) -> List[GeospatialAsset]:
        """
        List assets awaiting approval.

        Args:
            limit: Maximum results
            include_processing_incomplete: If True, include assets still processing

        Returns:
            List of GeospatialAsset in PENDING_REVIEW state
        """
        assets = self.asset_repo.list_by_approval_state(
            state=ApprovalState.PENDING_REVIEW,
            limit=limit
        )

        if not include_processing_incomplete:
            # Filter to only completed processing
            assets = [a for a in assets if a.processing_status == ProcessingStatus.COMPLETED]

        return assets

    def list_by_approval_state(
        self,
        approval_state: ApprovalState,
        limit: int = 100
    ) -> List[GeospatialAsset]:
        """
        List assets by approval state.

        Args:
            approval_state: State to filter by
            limit: Maximum results

        Returns:
            List of GeospatialAsset
        """
        return self.asset_repo.list_by_approval_state(
            state=approval_state,
            limit=limit
        )

    def get_approval_stats(self) -> Dict[str, int]:
        """
        Get counts of assets by approval_state.

        Returns:
            Dict like {'pending_review': 5, 'approved': 100, 'rejected': 2, 'revoked': 1}
        """
        return self.asset_repo.count_by_approval_state()

    # =========================================================================
    # STAC INTEGRATION
    # =========================================================================

    def _materialize_stac(
        self,
        asset: GeospatialAsset,
        reviewer: str,
        clearance_state: ClearanceState
    ) -> Dict[str, Any]:
        """
        Create pgSTAC item from cached STAC dict at approval time.

        19 FEB 2026: STAC as B2C materialized view.
        The STAC item dict was cached in cog_metadata.stac_item_json during processing.
        At approval, we:
        1. Read the cached dict
        2. Patch it with versioned ID and approval properties
        3. Build/upsert the STAC collection
        4. Insert the item into pgSTAC

        The cached dict uses the DRAFT cog_id (before assign_version renamed it).
        We reconstruct the draft cog_id deterministically from platform_refs.
        """
        if not asset.stac_item_id or not asset.stac_collection_id:
            return {
                'success': False,
                'error': 'Asset has no STAC item/collection ID'
            }

        try:
            from infrastructure.raster_metadata_repository import get_raster_metadata_repository
            from infrastructure.pgstac_repository import PgStacRepository
            from services.stac_collection import build_raster_stac_collection
            from services.platform_translation import generate_stac_item_id

            cog_repo = get_raster_metadata_repository()

            # Reconstruct the draft cog_id (before assign_version renamed it)
            # Draft STAC item IDs use version_id=None → "draft" placeholder
            platform_refs = asset.platform_refs or {}
            draft_cog_id = generate_stac_item_id(
                platform_refs.get('dataset_id', ''),
                platform_refs.get('resource_id', ''),
                None  # draft
            )

            # Read cached STAC item dict
            stac_item_json = cog_repo.get_stac_item_json(draft_cog_id)
            if not stac_item_json:
                logger.warning(f"No cached STAC item for draft cog_id={draft_cog_id}")
                return {
                    'success': False,
                    'error': f'STAC metadata not cached for {draft_cog_id} — resubmit data'
                }

            # Patch the dict with versioned ID and approval properties
            stac_item_json['id'] = asset.stac_item_id  # Versioned ID from assign_version
            stac_item_json['collection'] = asset.stac_collection_id

            now_iso = datetime.now(timezone.utc).isoformat()
            props = stac_item_json.setdefault('properties', {})
            props['geoetl:published'] = True
            props['geoetl:published_at'] = now_iso
            props['geoetl:approved_by'] = reviewer
            props['geoetl:clearance'] = clearance_state.value

            # Add version info from platform_refs
            version_id = platform_refs.get('version_id')
            if version_id:
                props['ddh:version_id'] = version_id

            # Build and upsert STAC collection
            pgstac = PgStacRepository()

            item_bbox = stac_item_json.get('bbox', [-180, -90, 180, 90])
            item_dt = props.get('datetime')
            collection_dict = build_raster_stac_collection(
                collection_id=asset.stac_collection_id,
                bbox=item_bbox,
                temporal_start=item_dt,
            )
            pgstac.insert_collection(collection_dict)
            logger.info(f"Collection upserted: {asset.stac_collection_id}")

            # Insert item into pgSTAC
            pgstac_id = pgstac.insert_item(stac_item_json, asset.stac_collection_id)
            logger.info(
                f"Materialized STAC item {asset.stac_item_id} in collection "
                f"{asset.stac_collection_id} (pgstac_id={pgstac_id})"
            )

            return {'success': True, 'pgstac_id': pgstac_id}

        except Exception as e:
            logger.error(f"Error materializing STAC item: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _delete_stac(self, asset: GeospatialAsset) -> Dict[str, Any]:
        """
        Delete pgSTAC item on revocation.

        19 FEB 2026: STAC as B2C materialized view.
        Approved = visible in catalog, not approved = invisible.
        Revocation deletes the item from pgSTAC entirely.
        The cached stac_item_json in cog_metadata is preserved for re-approval.

        Note: asset.stac_item_id is read BEFORE update_revocation() clears
        version info. The SQL update doesn't mutate the Python object in memory.
        """
        if not asset.stac_item_id or not asset.stac_collection_id:
            return {
                'success': True,
                'deleted': False,
                'reason': 'Asset has no STAC item/collection ID (never materialized)'
            }

        try:
            from infrastructure.pgstac_repository import PgStacRepository
            pgstac = PgStacRepository()

            deleted = pgstac.delete_item(asset.stac_collection_id, asset.stac_item_id)

            if deleted:
                logger.info(f"Deleted pgSTAC item {asset.stac_item_id}")
            else:
                logger.info(f"pgSTAC item {asset.stac_item_id} not found (never materialized)")

            return {'success': True, 'deleted': deleted}

        except Exception as e:
            logger.warning(f"Failed to delete STAC item on revocation: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # ADF INTEGRATION
    # =========================================================================

    def _trigger_adf_pipeline(self, asset: GeospatialAsset) -> Dict[str, Any]:
        """
        Trigger ADF pipeline for PUBLIC data export.

        Args:
            asset: The approved asset

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
                    'asset_id': asset.asset_id,
                    'stac_item_id': asset.stac_item_id,
                    'stac_collection_id': asset.stac_collection_id,
                    'data_type': asset.data_type,
                    'table_name': asset.table_name,
                    'blob_path': asset.blob_path
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
