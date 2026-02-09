# ============================================================================
# ASSET APPROVALS ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for asset approval routes
# PURPOSE: QA workflow endpoints for reviewing and approving assets
# CREATED: 16 JAN 2026
# UPDATED: 08 FEB 2026 - V0.8.11 AssetApprovalService refactor
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
Asset Approvals Admin Blueprint - QA workflow routes.

V0.8.11 Refactor (08 FEB 2026):
- Uses AssetApprovalService (GeospatialAsset-centric)
- GeospatialAsset.approval_state is the single source of truth
- Removed legacy DatasetApproval dependency
- Route parameter 'approval_id' now interpreted as 'asset_id'

Routes (5 total):
    List & Get (2):
        GET  /api/approvals           - List assets by approval state
        GET  /api/approvals/{id}      - Get specific asset

    Actions (3):
        POST /api/approvals/{id}/approve   - Approve asset
        POST /api/approvals/{id}/reject    - Reject asset
        POST /api/approvals/{id}/revoke    - Revoke approved asset

Clearance determines post-approval action:
    - OUO: Update STAC item with app:published=true
    - PUBLIC: Trigger ADF pipeline + update STAC
"""

import json
import azure.functions as func
from azure.functions import Blueprint

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
        from core.models.asset import ApprovalState, ClearanceState

        service = AssetApprovalService()

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

        # Get assets
        if approval_state:
            assets = service.list_by_approval_state(
                approval_state=approval_state,
                limit=limit
            )
        else:
            # Default: list pending review
            assets = service.list_pending_review(limit=limit)

        # Get status counts for summary
        counts = service.get_approval_stats()

        result = {
            'assets': [a.to_dict() for a in assets],
            'count': len(assets),
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
        logger.error(f"Error listing approvals: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


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
        from infrastructure.asset_repository import GeospatialAssetRepository

        asset_id = req.route_params.get('approval_id')
        if not asset_id:
            return func.HttpResponse(
                json.dumps({'error': 'asset_id is required'}),
                status_code=400,
                mimetype='application/json'
            )

        asset_repo = GeospatialAssetRepository()
        asset = asset_repo.get_by_id(asset_id)

        if not asset:
            return func.HttpResponse(
                json.dumps({'error': f"Asset not found: {asset_id}"}),
                status_code=404,
                mimetype='application/json'
            )

        return func.HttpResponse(
            json.dumps(asset.to_dict(), indent=2, default=str),
            status_code=200,
            mimetype='application/json'
        )

    except Exception as e:
        logger.error(f"Error getting asset: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


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
            "clearance_level": "ouo",            // Required: "ouo" or "public"
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
        - Updates STAC item with app:published=true
        - If PUBLIC clearance, triggers ADF pipeline
    """
    try:
        from services.asset_approval_service import AssetApprovalService
        from core.models.asset import ClearanceState

        asset_id = req.route_params.get('approval_id')
        if not asset_id:
            return func.HttpResponse(
                json.dumps({'error': 'asset_id is required'}),
                status_code=400,
                mimetype='application/json'
            )

        # Parse body
        try:
            body = req.get_json()
        except ValueError:
            body = {}

        reviewer = body.get('reviewer')
        if not reviewer:
            return func.HttpResponse(
                json.dumps({'error': 'reviewer is required in request body'}),
                status_code=400,
                mimetype='application/json'
            )

        clearance_level_str = body.get('clearance_level')
        if not clearance_level_str:
            return func.HttpResponse(
                json.dumps({'error': "clearance_level is required. Must be 'ouo' or 'public'"}),
                status_code=400,
                mimetype='application/json'
            )

        # Parse clearance level
        try:
            clearance_state = ClearanceState(clearance_level_str.lower())
            if clearance_state == ClearanceState.UNCLEARED:
                return func.HttpResponse(
                    json.dumps({'error': "clearance_level must be 'ouo' or 'public', not 'uncleared'"}),
                    status_code=400,
                    mimetype='application/json'
                )
        except ValueError:
            return func.HttpResponse(
                json.dumps({'error': f"Invalid clearance_level: '{clearance_level_str}'. Must be 'ouo' or 'public'"}),
                status_code=400,
                mimetype='application/json'
            )

        notes = body.get('notes')

        logger.info(f"Approve request: {asset_id[:16]}... by {reviewer} (clearance: {clearance_state.value})")

        service = AssetApprovalService()
        result = service.approve_asset(
            asset_id=asset_id,
            reviewer=reviewer,
            clearance_state=clearance_state,
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
        logger.error(f"Error approving asset: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


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

        asset_id = req.route_params.get('approval_id')
        if not asset_id:
            return func.HttpResponse(
                json.dumps({'error': 'asset_id is required'}),
                status_code=400,
                mimetype='application/json'
            )

        # Parse body
        try:
            body = req.get_json()
        except ValueError:
            body = {}

        reviewer = body.get('reviewer')
        if not reviewer:
            return func.HttpResponse(
                json.dumps({'error': 'reviewer is required in request body'}),
                status_code=400,
                mimetype='application/json'
            )

        reason = body.get('reason')
        if not reason:
            return func.HttpResponse(
                json.dumps({'error': 'reason is required in request body'}),
                status_code=400,
                mimetype='application/json'
            )

        logger.info(f"Reject request: {asset_id[:16]}... by {reviewer}")

        service = AssetApprovalService()
        result = service.reject_asset(
            asset_id=asset_id,
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
        logger.error(f"Error rejecting asset: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


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

        asset_id = req.route_params.get('approval_id')
        if not asset_id:
            return func.HttpResponse(
                json.dumps({'error': 'asset_id is required'}),
                status_code=400,
                mimetype='application/json'
            )

        # Parse body
        try:
            body = req.get_json()
        except ValueError:
            body = {}

        revoker = body.get('revoker')
        if not revoker:
            return func.HttpResponse(
                json.dumps({'error': 'revoker is required in request body'}),
                status_code=400,
                mimetype='application/json'
            )

        reason = body.get('reason')
        if not reason:
            return func.HttpResponse(
                json.dumps({'error': 'reason is required in request body'}),
                status_code=400,
                mimetype='application/json'
            )

        logger.warning(f"AUDIT: Revoke request: {asset_id[:16]}... by {revoker}")

        service = AssetApprovalService()
        result = service.revoke_asset(
            asset_id=asset_id,
            revoker=revoker,
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
        logger.error(f"Error revoking asset: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


# Module exports
__all__ = ['bp']
