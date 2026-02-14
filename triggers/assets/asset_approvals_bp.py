# ============================================================================
# ASSET APPROVALS BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Asset-centric approval endpoints
# PURPOSE: Approval workflow operating directly on GeospatialAsset (Aggregate Root)
# CREATED: 08 FEB 2026 (V0.8.11 - Approval Consolidation Phase 3)
# EXPORTS: bp (Blueprint)
# DEPENDENCIES: services.asset_approval_service
# ============================================================================
"""
Asset Approvals Blueprint.

V0.8+ asset-centric approval endpoints that operate directly on GeospatialAsset.
This replaces the legacy /api/approvals/* and /api/platform/approve|reject|revoke
endpoints that used the separate DatasetApproval table.

Design Principle:
    GeospatialAsset is the Aggregate Root - all approval state lives on the asset.
    No separate approval records needed.

Routes (7 total):
    Actions (3):
        POST /api/assets/{asset_id}/approve   - Approve asset for publication
        POST /api/assets/{asset_id}/reject    - Reject asset
        POST /api/assets/{asset_id}/revoke    - Revoke approved asset (unpublish)

    Query (3):
        GET  /api/assets/pending-review       - List assets awaiting approval
        GET  /api/assets/approval-stats       - Get counts by approval state
        GET  /api/assets/{asset_id}/approval  - Get approval state for asset

    Batch (1):
        GET  /api/assets/by-approval-state    - List assets by approval state

Endpoint Pattern:
    Asset-centric: /api/assets/{asset_id}/action
    vs Legacy: /api/approvals/{approval_id}/action
"""

import json
import azure.functions as func
from azure.functions import Blueprint

from triggers.http_base import parse_request_json
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AssetApprovals")

bp = Blueprint()


# ============================================================================
# APPROVAL ACTIONS (3 routes)
# ============================================================================

@bp.route(route="assets/{asset_id}/approve", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def approve_asset(req: func.HttpRequest) -> func.HttpResponse:
    """
    Approve an asset for publication.

    POST /api/assets/{asset_id}/approve

    Path Parameters:
        asset_id: GeospatialAsset ID to approve

    Request Body:
        {
            "reviewer": "user@example.com",     // Required: Who is approving
            "clearance_state": "ouo",           // Required: "ouo" or "public"
            "notes": "Looks good"               // Optional: Review notes
        }

    Clearance States:
        - "ouo": Official Use Only - internal access only
        - "public": Public access - triggers ADF pipeline for external export

    Response (success):
        {
            "success": true,
            "asset": {...},                     // Updated GeospatialAsset
            "action": "approved_ouo",           // or "approved_public_adf_triggered"
            "stac_updated": true,
            "adf_run_id": "..."                 // If PUBLIC
        }

    Response (error):
        {
            "success": false,
            "error": "Cannot approve: approval_state is 'approved', expected 'pending_review'",
            "error_type": "InvalidStateTransition"
        }
    """
    asset_id = req.route_params.get('asset_id')
    if not asset_id:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "asset_id is required in path",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    logger.info(f"Asset approve endpoint called for {asset_id[:16]}...")

    try:
        req_body = parse_request_json(req)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Invalid JSON in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    # Extract and validate parameters
    reviewer = req_body.get('reviewer')
    clearance_state_str = req_body.get('clearance_state')
    notes = req_body.get('notes')

    if not reviewer:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "reviewer is required in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    if not clearance_state_str:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "clearance_state is required. Must be 'ouo' or 'public'",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    # Parse clearance state
    try:
        from core.models.asset import ClearanceState
        clearance_state = ClearanceState(clearance_state_str.lower())
        if clearance_state == ClearanceState.UNCLEARED:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "clearance_state must be 'ouo' or 'public', not 'uncleared'",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": f"Invalid clearance_state: '{clearance_state_str}'. Must be 'ouo' or 'public'",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    try:
        from services.asset_approval_service import AssetApprovalService
        service = AssetApprovalService()

        logger.info(f"Approving asset {asset_id[:16]}... by {reviewer} (clearance: {clearance_state.value})")

        result = service.approve_asset(
            asset_id=asset_id,
            reviewer=reviewer,
            clearance_state=clearance_state,
            notes=notes
        )

        if result.get('success'):
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )
        else:
            # Determine appropriate status code
            error_msg = result.get('error', '')
            if 'not found' in error_msg.lower():
                status_code = 404
            elif 'cannot approve' in error_msg.lower():
                status_code = 409  # Conflict - state transition error
            else:
                status_code = 400

            result['error_type'] = 'InvalidStateTransition' if 'cannot' in error_msg.lower() else 'ApprovalError'
            return func.HttpResponse(
                json.dumps(result),
                status_code=status_code,
                headers={"Content-Type": "application/json"}
            )

    except Exception as e:
        logger.error(f"Asset approve failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


@bp.route(route="assets/{asset_id}/reject", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def reject_asset(req: func.HttpRequest) -> func.HttpResponse:
    """
    Reject an asset.

    POST /api/assets/{asset_id}/reject

    Path Parameters:
        asset_id: GeospatialAsset ID to reject

    Request Body:
        {
            "reviewer": "user@example.com",        // Required: Who is rejecting
            "reason": "Data quality issue found"   // Required: Rejection reason
        }

    Response (success):
        {
            "success": true,
            "asset": {...}                         // Updated GeospatialAsset
        }

    Response (error):
        {
            "success": false,
            "error": "Cannot reject: approval_state is 'approved', expected 'pending_review'",
            "error_type": "InvalidStateTransition"
        }
    """
    asset_id = req.route_params.get('asset_id')
    if not asset_id:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "asset_id is required in path",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    logger.info(f"Asset reject endpoint called for {asset_id[:16]}...")

    try:
        req_body = parse_request_json(req)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Invalid JSON in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    # Extract and validate parameters
    reviewer = req_body.get('reviewer')
    reason = req_body.get('reason')

    if not reviewer:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "reviewer is required in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    if not reason or not reason.strip():
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "reason is required for audit trail",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    try:
        from services.asset_approval_service import AssetApprovalService
        service = AssetApprovalService()

        logger.info(f"Rejecting asset {asset_id[:16]}... by {reviewer}")

        result = service.reject_asset(
            asset_id=asset_id,
            reviewer=reviewer,
            reason=reason
        )

        if result.get('success'):
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )
        else:
            error_msg = result.get('error', '')
            if 'not found' in error_msg.lower():
                status_code = 404
            elif 'cannot reject' in error_msg.lower():
                status_code = 409
            else:
                status_code = 400

            result['error_type'] = 'InvalidStateTransition' if 'cannot' in error_msg.lower() else 'RejectionError'
            return func.HttpResponse(
                json.dumps(result),
                status_code=status_code,
                headers={"Content-Type": "application/json"}
            )

    except Exception as e:
        logger.error(f"Asset reject failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


@bp.route(route="assets/{asset_id}/revoke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def revoke_asset(req: func.HttpRequest) -> func.HttpResponse:
    """
    Revoke a previously approved asset (unpublish).

    POST /api/assets/{asset_id}/revoke

    This is a terminal state - to re-publish, submit a new version.
    IMPORTANT: This is an audit-logged operation.

    Path Parameters:
        asset_id: GeospatialAsset ID to revoke

    Request Body:
        {
            "revoker": "user@example.com",         // Required: Who is revoking
            "reason": "Data quality issue found"   // Required: Revocation reason
        }

    Response (success):
        {
            "success": true,
            "asset": {...},                        // Updated GeospatialAsset
            "stac_updated": true,
            "warning": "Approved asset has been revoked - this action is logged for audit"
        }

    Response (error):
        {
            "success": false,
            "error": "Cannot revoke: approval_state is 'pending_review', expected 'approved'",
            "error_type": "InvalidStateTransition"
        }
    """
    asset_id = req.route_params.get('asset_id')
    if not asset_id:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "asset_id is required in path",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    logger.info(f"Asset revoke endpoint called for {asset_id[:16]}...")

    try:
        req_body = parse_request_json(req)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Invalid JSON in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    # Extract and validate parameters
    revoker = req_body.get('revoker')
    reason = req_body.get('reason')

    if not revoker:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "revoker is required in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    if not reason or not reason.strip():
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "reason is required for audit trail",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    try:
        from services.asset_approval_service import AssetApprovalService
        service = AssetApprovalService()

        logger.warning(f"AUDIT: Revoking asset {asset_id[:16]}... by {revoker}. Reason: {reason}")

        result = service.revoke_asset(
            asset_id=asset_id,
            revoker=revoker,
            reason=reason
        )

        if result.get('success'):
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )
        else:
            error_msg = result.get('error', '')
            if 'not found' in error_msg.lower():
                status_code = 404
            elif 'cannot revoke' in error_msg.lower():
                status_code = 409
            else:
                status_code = 400

            result['error_type'] = 'InvalidStateTransition' if 'cannot' in error_msg.lower() else 'RevocationError'
            return func.HttpResponse(
                json.dumps(result),
                status_code=status_code,
                headers={"Content-Type": "application/json"}
            )

    except Exception as e:
        logger.error(f"Asset revoke failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# QUERY ROUTES (3 routes)
# ============================================================================

@bp.route(route="assets/pending-review", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_pending_review(req: func.HttpRequest) -> func.HttpResponse:
    """
    List assets awaiting approval.

    GET /api/assets/pending-review?limit=50&include_incomplete=false

    Query Parameters:
        limit: Maximum results (default: 50, max: 200)
        include_incomplete: Include assets still processing (default: false)

    Response:
        {
            "success": true,
            "assets": [...],
            "count": 25,
            "limit": 50,
            "filters": {
                "include_incomplete": false
            }
        }
    """
    logger.info("Assets pending-review endpoint called")

    try:
        # Parse query parameters
        limit = min(int(req.params.get('limit', 50)), 200)
        include_incomplete = req.params.get('include_incomplete', 'false').lower() == 'true'

        from services.asset_approval_service import AssetApprovalService
        service = AssetApprovalService()

        assets = service.list_pending_review(
            limit=limit,
            include_processing_incomplete=include_incomplete
        )

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "assets": [a.to_dict() for a in assets],
                "count": len(assets),
                "limit": limit,
                "filters": {
                    "include_incomplete": include_incomplete
                }
            }, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"List pending-review failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


@bp.route(route="assets/approval-stats", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_approval_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get counts of assets by approval_state.

    GET /api/assets/approval-stats

    Response:
        {
            "success": true,
            "stats": {
                "pending_review": 5,
                "approved": 100,
                "rejected": 2,
                "revoked": 1
            },
            "total": 108
        }
    """
    logger.info("Assets approval-stats endpoint called")

    try:
        from services.asset_approval_service import AssetApprovalService
        service = AssetApprovalService()

        stats = service.get_approval_stats()
        total = sum(stats.values())

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "stats": stats,
                "total": total
            }, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Get approval-stats failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


@bp.route(route="assets/{asset_id}/approval", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_asset_approval(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get approval state for a specific asset.

    GET /api/assets/{asset_id}/approval

    Response:
        {
            "success": true,
            "asset_id": "...",
            "approval_state": "approved",
            "clearance_state": "ouo",
            "reviewer": "user@example.com",
            "reviewed_at": "2026-02-08T...",
            "approval_notes": "Looks good",
            "processing_status": "completed"
        }
    """
    asset_id = req.route_params.get('asset_id')
    if not asset_id:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "asset_id is required in path",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    logger.info(f"Get asset approval state for {asset_id[:16]}...")

    try:
        from infrastructure.asset_repository import GeospatialAssetRepository
        repo = GeospatialAssetRepository()

        asset = repo.get_by_id(asset_id)
        if not asset:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Asset not found: {asset_id}",
                    "error_type": "NotFound"
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "asset_id": asset.asset_id,
                "approval_state": asset.approval_state.value if asset.approval_state else None,
                "clearance_state": asset.clearance_state.value if asset.clearance_state else None,
                "reviewer": asset.reviewer,
                "reviewed_at": asset.reviewed_at.isoformat() if asset.reviewed_at else None,
                "approval_notes": asset.approval_notes,
                "rejection_reason": asset.rejection_reason,
                "processing_status": asset.processing_status.value if asset.processing_status else None,
                "can_approve": asset.can_approve(),
                "can_reject": asset.can_reject(),
                "can_revoke": asset.can_revoke(),
                "is_revoked": asset.is_revoked()
            }, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Get asset approval failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# BATCH QUERY (1 route)
# ============================================================================

@bp.route(route="assets/by-approval-state", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_by_approval_state(req: func.HttpRequest) -> func.HttpResponse:
    """
    List assets by approval state.

    GET /api/assets/by-approval-state?state=approved&limit=100

    Query Parameters:
        state: Required - pending_review, approved, rejected, revoked
        limit: Maximum results (default: 100, max: 500)

    Response:
        {
            "success": true,
            "assets": [...],
            "count": 50,
            "state": "approved",
            "limit": 100
        }
    """
    logger.info("Assets by-approval-state endpoint called")

    try:
        # Parse query parameters
        state_str = req.params.get('state')
        limit = min(int(req.params.get('limit', 100)), 500)

        if not state_str:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "state query parameter is required. Valid values: pending_review, approved, rejected, revoked",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Parse state enum
        try:
            from core.models.asset import ApprovalState
            approval_state = ApprovalState(state_str.lower())
        except ValueError:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Invalid state: '{state_str}'. Valid values: pending_review, approved, rejected, revoked",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        from services.asset_approval_service import AssetApprovalService
        service = AssetApprovalService()

        assets = service.list_by_approval_state(
            approval_state=approval_state,
            limit=limit
        )

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "assets": [a.to_dict() for a in assets],
                "count": len(assets),
                "state": state_str,
                "limit": limit
            }, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"List by-approval-state failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# Module exports
__all__ = ['bp']
