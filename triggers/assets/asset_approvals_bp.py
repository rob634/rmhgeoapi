# ============================================================================
# ASSET APPROVALS BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Asset-centric approval endpoints (V0.9 Release-based)
# PURPOSE: Approval workflow resolving asset_id to release_id, then operating on AssetRelease
# CREATED: 08 FEB 2026 (V0.8.11 - Approval Consolidation Phase 3)
# LAST_REVIEWED: 21 FEB 2026 (V0.9 Asset/Release entity split)
# EXPORTS: bp (Blueprint)
# DEPENDENCIES: services.asset_approval_service, infrastructure.ReleaseRepository
# ============================================================================
"""
Asset Approvals Blueprint -- V0.9 Release-Based Approval.

V0.9: URLs still use asset_id for external API stability, but internally
each action resolves asset_id -> release_id via ReleaseRepository, then
delegates to AssetApprovalService which operates on AssetRelease.

Design Principle:
    AssetRelease is the approval target. All approval state lives on the release.
    The Asset (identity container) is never mutated during approval.

Routes (7 total):
    Actions (3):
        POST /api/assets/{asset_id}/approve   - Approve release for publication
        POST /api/assets/{asset_id}/reject    - Reject release
        POST /api/assets/{asset_id}/revoke    - Revoke approved release (unpublish)

    Query (3):
        GET  /api/assets/pending-review       - List releases awaiting approval
        GET  /api/assets/approval-stats       - Get counts by approval state
        GET  /api/assets/{asset_id}/approval  - Get approval state for asset + releases

    Batch (1):
        GET  /api/assets/by-approval-state    - List releases by approval state

Endpoint Pattern:
    Asset-centric URLs: /api/assets/{asset_id}/action
    Internal: resolve asset_id -> release_id, operate on release
"""

import json
import azure.functions as func
from azure.functions import Blueprint

from triggers.http_base import parse_request_json, safe_error_response
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
    version_id = req_body.get('version_id')  # Optional: auto-generated from ordinal if not provided

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
        from infrastructure import ReleaseRepository

        # V0.9: Resolve asset_id -> release_id (get draft or latest unapproved)
        release_repo = ReleaseRepository()
        release = release_repo.get_draft(asset_id)
        if not release:
            release = release_repo.get_latest(asset_id)
        if not release:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"No release found for asset {asset_id}",
                    "error_type": "NotFound"
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        service = AssetApprovalService()

        # Auto-generate version_id from ordinal if not provided in request body
        if not version_id and release.version_ordinal:
            version_id = f"v{release.version_ordinal}"
        elif not version_id:
            version_id = "v1"  # Safe default for legacy releases without ordinal

        logger.info(f"Approving release {release.release_id[:16]}... (asset {asset_id[:16]}...) by {reviewer} (clearance: {clearance_state.value}, version: {version_id})")

        result = service.approve_release(
            release_id=release.release_id,
            reviewer=reviewer,
            clearance_state=clearance_state,
            version_id=version_id,
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
        return safe_error_response(500, logger, "Asset approve failed", exc=e)


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
        from infrastructure import ReleaseRepository

        # V0.9: Resolve asset_id -> release_id (get draft or latest unapproved)
        release_repo = ReleaseRepository()
        release = release_repo.get_draft(asset_id)
        if not release:
            release = release_repo.get_latest(asset_id)
        if not release:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"No release found for asset {asset_id}",
                    "error_type": "NotFound"
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        service = AssetApprovalService()

        logger.info(f"Rejecting release {release.release_id[:16]}... (asset {asset_id[:16]}...) by {reviewer}")

        result = service.reject_release(
            release_id=release.release_id,
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
        return safe_error_response(500, logger, "Asset reject failed", exc=e)


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
        from infrastructure import ReleaseRepository

        # V0.9: Resolve asset_id -> release_id (for revoke, get latest approved release)
        release_repo = ReleaseRepository()
        release = release_repo.get_latest(asset_id)  # get_latest returns approved release
        if not release:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"No approved release found for asset {asset_id}",
                    "error_type": "NotFound"
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        service = AssetApprovalService()

        logger.warning(f"AUDIT: Revoking release {release.release_id[:16]}... (asset {asset_id[:16]}...) by {revoker}. Reason: {reason}")

        result = service.revoke_release(
            release_id=release.release_id,
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
        return safe_error_response(500, logger, "Asset revoke failed", exc=e)


# ============================================================================
# QUERY ROUTES (3 routes)
# ============================================================================

@bp.route(route="assets/pending-review", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_pending_review(req: func.HttpRequest) -> func.HttpResponse:
    """
    List releases awaiting approval.

    GET /api/assets/pending-review?limit=50

    V0.9: Returns AssetRelease objects with processing_status=COMPLETED
    and approval_state=PENDING_REVIEW.

    Query Parameters:
        limit: Maximum results (default: 50, max: 200)

    Response:
        {
            "success": true,
            "releases": [...],
            "count": 25,
            "limit": 50
        }
    """
    logger.info("Assets pending-review endpoint called")

    try:
        # Parse query parameters
        limit = min(int(req.params.get('limit', 50)), 200)

        from services.asset_approval_service import AssetApprovalService
        service = AssetApprovalService()

        releases = service.list_pending_review(limit=limit)

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "releases": [r.to_dict() for r in releases],
                "count": len(releases),
                "limit": limit
            }, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        return safe_error_response(500, logger, "List pending-review failed", exc=e)


@bp.route(route="assets/approval-stats", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_approval_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get counts of releases by approval_state.

    GET /api/assets/approval-stats

    V0.9: Counts AssetRelease records by approval_state.

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
        return safe_error_response(500, logger, "Get approval-stats failed", exc=e)


@bp.route(route="assets/{asset_id}/approval", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_asset_approval(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get approval state for a specific asset and its releases.

    GET /api/assets/{asset_id}/approval

    V0.9: Returns asset identity info plus all releases with their
    approval states. The primary release (draft or latest) is highlighted.

    Response:
        {
            "success": true,
            "asset_id": "...",
            "asset": {...},
            "releases": [...],
            "primary_release": {...}
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
        from infrastructure import AssetRepository, ReleaseRepository

        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(asset_id)
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

        release_repo = ReleaseRepository()
        releases = release_repo.list_by_asset(asset_id)

        # Find primary release (draft first, then latest)
        primary = release_repo.get_draft(asset_id)
        if not primary:
            primary = release_repo.get_latest(asset_id)

        response_data = {
            "success": True,
            "asset_id": asset.asset_id,
            "asset": asset.to_dict(),
            "releases": [r.to_dict() for r in releases],
            "release_count": len(releases),
        }

        if primary:
            response_data["primary_release"] = primary.to_dict()

        return func.HttpResponse(
            json.dumps(response_data, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        return safe_error_response(500, logger, "Get asset approval failed", exc=e)


# ============================================================================
# BATCH QUERY (1 route)
# ============================================================================

@bp.route(route="assets/by-approval-state", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_by_approval_state(req: func.HttpRequest) -> func.HttpResponse:
    """
    List releases by approval state.

    GET /api/assets/by-approval-state?state=approved&limit=100

    V0.9: Returns AssetRelease objects filtered by approval_state.

    Query Parameters:
        state: Required - pending_review, approved, rejected, revoked
        limit: Maximum results (default: 100, max: 500)

    Response:
        {
            "success": true,
            "releases": [...],
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

        from infrastructure import ReleaseRepository
        release_repo = ReleaseRepository()

        releases = release_repo.list_by_approval_state(
            state=approval_state,
            limit=limit
        )

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "releases": [r.to_dict() for r in releases],
                "count": len(releases),
                "state": state_str,
                "limit": limit
            }, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        return safe_error_response(500, logger, "List by-approval-state failed", exc=e)


# Module exports
__all__ = ['bp']
