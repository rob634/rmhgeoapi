# ============================================================================
# ASSET APPROVALS ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for asset approval routes (V0.9 Release-based)
# PURPOSE: QA workflow endpoints for reviewing and approving releases
# CREATED: 16 JAN 2026
# LAST_REVIEWED: 21 FEB 2026 (V0.9 Asset/Release entity split)
# EXPORTS: bp (Blueprint)
# DEPENDENCIES: services.asset_approval_service, infrastructure.ReleaseRepository
# ============================================================================
"""
Asset Approvals Admin Blueprint -- V0.9 Release-Based Approval.

V0.9 Refactor (21 FEB 2026):
- Uses AssetApprovalService operating on AssetRelease (not Asset)
- Route parameter 'approval_id' interpreted as 'asset_id', then resolved to release_id
- Approval state lives on AssetRelease, not Asset

Routes (5 total):
    List & Get (2):
        GET  /api/approvals           - List releases by approval state
        GET  /api/approvals/{id}      - Get specific asset + releases

    Actions (3):
        POST /api/approvals/{id}/approve   - Approve release
        POST /api/approvals/{id}/reject    - Reject release
        POST /api/approvals/{id}/revoke    - Revoke approved release

Clearance determines post-approval action:
    - OUO: Update STAC item with geoetl:published=true
    - PUBLIC: Trigger ADF pipeline + update STAC
"""

import json
import azure.functions as func
from azure.functions import Blueprint

from triggers.http_base import parse_request_json, safe_error_response
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "ApprovalsAdmin")

bp = Blueprint()


# ============================================================================
# LIST & GET (2 routes)
# ============================================================================

@bp.route(route="approvals", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_approvals(req: func.HttpRequest) -> func.HttpResponse:
    """
    List assets by approval state with optional filters.

    GET /api/approvals?status=pending_review&limit=50&offset=0

    Query Parameters:
        status: Filter by approval_state (pending_review, approved, rejected, revoked)
        clearance: Filter by clearance_state (uncleared, ouo, public)
        limit: Maximum results (default: 50, max: 200)
        offset: Pagination offset (default: 0)

    Returns:
        JSON array of asset records
    """
    try:
        from services.asset_approval_service import AssetApprovalService
        from infrastructure import ReleaseRepository
        from core.models.asset import ApprovalState, ClearanceState

        service = AssetApprovalService()
        release_repo = ReleaseRepository()

        # Parse query parameters
        status_str = req.params.get('status')
        clearance_str = req.params.get('clearance')
        limit = min(int(req.params.get('limit', 50)), 200)
        offset = int(req.params.get('offset', 0))

        # Convert string to enums
        approval_state = None
        if status_str:
            # Normalize status names (legacy used "pending", new uses "pending_review")
            status_map = {
                'pending': 'pending_review',
                'pending_review': 'pending_review',
                'approved': 'approved',
                'rejected': 'rejected',
                'revoked': 'revoked'
            }
            normalized = status_map.get(status_str.lower())
            if not normalized:
                return func.HttpResponse(
                    json.dumps({
                        'error': f"Invalid status '{status_str}'. Must be: pending_review, approved, rejected, revoked"
                    }),
                    status_code=400,
                    mimetype='application/json'
                )
            try:
                approval_state = ApprovalState(normalized)
            except ValueError:
                return func.HttpResponse(
                    json.dumps({
                        'error': f"Invalid status '{status_str}'"
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

        # V0.9: Get releases (not assets)
        if approval_state:
            releases = release_repo.list_by_approval_state(
                state=approval_state,
                limit=limit
            )
        else:
            # Default: list pending review
            releases = service.list_pending_review(limit=limit)

        # Get status counts for summary
        counts = service.get_approval_stats()

        result = {
            'releases': [r.to_dict() for r in releases],
            'count': len(releases),
            'limit': limit,
            'offset': offset,
            'status_counts': counts
        }

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            mimetype='application/json'
        )

    except Exception as e:
        return safe_error_response(500, logger, "Error listing approvals", exc=e)


@bp.route(route="approvals/{approval_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_approval(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get a specific asset by ID.

    GET /api/approvals/{asset_id}

    Note: Route uses 'approval_id' for backwards compatibility,
    but parameter is now interpreted as asset_id.

    Returns:
        Asset record with full details
    """
    try:
        from infrastructure import AssetRepository, ReleaseRepository

        asset_id = req.route_params.get('approval_id')
        if not asset_id:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'asset_id is required', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        # V0.9: Return asset + all releases
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(asset_id)

        if not asset:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': f"Asset not found: {asset_id}", 'error_type': 'NotFound'}),
                status_code=404,
                mimetype='application/json'
            )

        release_repo = ReleaseRepository()
        releases = release_repo.list_by_asset(asset_id)

        result = {
            'asset': asset.to_dict(),
            'releases': [r.to_dict() for r in releases],
            'release_count': len(releases),
        }

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            mimetype='application/json'
        )

    except Exception as e:
        return safe_error_response(500, logger, "Error getting asset", exc=e)


# ============================================================================
# ACTIONS (3 routes)
# ============================================================================

@bp.route(route="approvals/{approval_id}/approve", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def approve_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """
    Approve an asset for publication.

    POST /api/approvals/{asset_id}/approve

    Body:
        {
            "reviewer": "analyst@example.com",   // Required
            "clearance_state": "ouo",            // Required: "ouo" or "public"
            "notes": "Looks good"                // Optional
        }

    Returns:
        {
            "success": true,
            "asset": {...},
            "action": "approved_ouo" | "approved_public_adf_triggered",
            "adf_run_id": "..." (if PUBLIC)
        }

    Actions:
        - Updates STAC item with geoetl:published=true
        - If PUBLIC clearance, triggers ADF pipeline
    """
    try:
        from services.asset_approval_service import AssetApprovalService
        from infrastructure import ReleaseRepository
        from core.models.asset import ClearanceState

        asset_id = req.route_params.get('approval_id')
        if not asset_id:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'asset_id is required', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        # Parse body
        try:
            body = parse_request_json(req)
        except ValueError:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'Invalid JSON body', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        reviewer = body.get('reviewer')
        if not reviewer:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'reviewer is required in request body', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        clearance_level_str = body.get('clearance_state') or body.get('clearance_level')
        if not clearance_level_str:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': "clearance_state is required. Must be 'ouo' or 'public'", 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        # Parse clearance state
        try:
            clearance_state = ClearanceState(clearance_level_str.lower())
            if clearance_state == ClearanceState.UNCLEARED:
                return func.HttpResponse(
                    json.dumps({'success': False, 'error': "clearance_state must be 'ouo' or 'public', not 'uncleared'", 'error_type': 'ValidationError'}),
                    status_code=400,
                    mimetype='application/json'
                )
        except ValueError:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': f"Invalid clearance_state: '{clearance_level_str}'. Must be 'ouo' or 'public'", 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        notes = body.get('notes')
        version_id = body.get('version_id')  # Optional: auto-generated from ordinal if not provided

        # V0.9: Resolve asset_id -> release_id
        release_repo = ReleaseRepository()
        release = release_repo.get_draft(asset_id)
        if not release:
            release = release_repo.get_latest(asset_id)
        if not release:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': f'No release found for asset {asset_id}', 'error_type': 'NotFound'}),
                status_code=404,
                mimetype='application/json'
            )

        # Auto-generate version_id from ordinal if not provided in request body
        if not version_id and release.version_ordinal:
            version_id = f"v{release.version_ordinal}"
        elif not version_id:
            version_id = "v1"  # Safe default for legacy releases without ordinal

        logger.info(f"Approve request: release {release.release_id[:16]}... (asset {asset_id[:16]}...) by {reviewer} (clearance: {clearance_state.value}, version: {version_id})")

        service = AssetApprovalService()
        result = service.approve_release(
            release_id=release.release_id,
            reviewer=reviewer,
            clearance_state=clearance_state,
            version_id=version_id,
            notes=notes
        )

        if result['success']:
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=200,
                mimetype='application/json'
            )
        else:
            status_code = 404 if 'not found' in result.get('error', '').lower() else 400
            return func.HttpResponse(
                json.dumps(result),
                status_code=status_code,
                mimetype='application/json'
            )

    except Exception as e:
        return safe_error_response(500, logger, "Error approving asset", exc=e)


@bp.route(route="approvals/{approval_id}/reject", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def reject_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """
    Reject an asset.

    POST /api/approvals/{asset_id}/reject

    Body:
        {
            "reviewer": "analyst@example.com",  // Required
            "reason": "Data quality issue"      // Required
        }

    Returns:
        {
            "success": true,
            "asset": {...}
        }
    """
    try:
        from services.asset_approval_service import AssetApprovalService
        from infrastructure import ReleaseRepository

        asset_id = req.route_params.get('approval_id')
        if not asset_id:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'asset_id is required', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        # Parse body
        try:
            body = parse_request_json(req)
        except ValueError:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'Invalid JSON body', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        reviewer = body.get('reviewer')
        if not reviewer:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'reviewer is required in request body', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        reason = body.get('reason')
        if not reason:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'reason is required in request body', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        # V0.9: Resolve asset_id -> release_id
        release_repo = ReleaseRepository()
        release = release_repo.get_draft(asset_id)
        if not release:
            release = release_repo.get_latest(asset_id)
        if not release:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': f'No release found for asset {asset_id}', 'error_type': 'NotFound'}),
                status_code=404,
                mimetype='application/json'
            )

        logger.info(f"Reject request: release {release.release_id[:16]}... (asset {asset_id[:16]}...) by {reviewer}")

        service = AssetApprovalService()
        result = service.reject_release(
            release_id=release.release_id,
            reviewer=reviewer,
            reason=reason
        )

        if result['success']:
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=200,
                mimetype='application/json'
            )
        else:
            status_code = 404 if 'not found' in result.get('error', '').lower() else 400
            return func.HttpResponse(
                json.dumps(result),
                status_code=status_code,
                mimetype='application/json'
            )

    except Exception as e:
        return safe_error_response(500, logger, "Error rejecting asset", exc=e)


@bp.route(route="approvals/{approval_id}/revoke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def revoke_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """
    Revoke an approved asset (unapprove).

    POST /api/approvals/{asset_id}/revoke

    Body:
        {
            "revoker": "analyst@example.com",  // Required
            "reason": "Data issue found"       // Required
        }

    Returns:
        {
            "success": true,
            "asset": {...},
            "stac_updated": true,
            "warning": "Approved asset has been revoked..."
        }
    """
    try:
        from services.asset_approval_service import AssetApprovalService
        from infrastructure import ReleaseRepository

        asset_id = req.route_params.get('approval_id')
        if not asset_id:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'asset_id is required', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        # Parse body
        try:
            body = parse_request_json(req)
        except ValueError:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'Invalid JSON body', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        # Standardized: accept 'reviewer' as the actor field for all operations
        reviewer = body.get('reviewer') or body.get('revoker')
        if not reviewer:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'reviewer is required in request body', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        reason = body.get('reason')
        if not reason:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': 'reason is required in request body', 'error_type': 'ValidationError'}),
                status_code=400,
                mimetype='application/json'
            )

        # V0.9: Resolve asset_id -> release_id (for revoke, get latest approved release)
        release_repo = ReleaseRepository()
        release = release_repo.get_latest(asset_id)  # get_latest returns approved release
        if not release:
            return func.HttpResponse(
                json.dumps({'success': False, 'error': f'No approved release found for asset {asset_id}', 'error_type': 'NotFound'}),
                status_code=404,
                mimetype='application/json'
            )

        logger.warning(f"AUDIT: Revoke request: release {release.release_id[:16]}... (asset {asset_id[:16]}...) by {reviewer}")

        service = AssetApprovalService()
        result = service.revoke_release(
            release_id=release.release_id,
            revoker=reviewer,
            reason=reason
        )

        if result['success']:
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=200,
                mimetype='application/json'
            )
        else:
            status_code = 404 if 'not found' in result.get('error', '').lower() else 400
            return func.HttpResponse(
                json.dumps(result),
                status_code=status_code,
                mimetype='application/json'
            )

    except Exception as e:
        return safe_error_response(500, logger, "Error revoking asset", exc=e)


# Module exports
__all__ = ['bp']
