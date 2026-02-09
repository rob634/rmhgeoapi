# ============================================================================
# APPROVAL PLATFORM TRIGGERS
# ============================================================================
# STATUS: Trigger - HTTP endpoints for dataset approval workflow
# PURPOSE: Platform API for approving and revoking dataset approvals
# LAST_REVIEWED: 08 FEB 2026
# EXPORTS: platform_approve, platform_reject, platform_revoke, platform_approvals_list
# DEPENDENCIES: services.asset_approval_service
# ============================================================================
"""
Approval Platform Triggers.

HTTP endpoints for the dataset approval workflow:
- POST /api/platform/approve - Approve a pending dataset
- POST /api/platform/reject - Reject a pending dataset
- POST /api/platform/revoke - Revoke an approved dataset (unapprove)
- GET /api/platform/approvals - List approvals with filters

V0.8.11 Refactor (08 FEB 2026):
- Uses AssetApprovalService (GeospatialAsset-centric)
- GeospatialAsset.approval_state is the single source of truth
- Removed legacy DatasetApproval dependency

These are synchronous operations (no async jobs) since they're simple
state changes to approval records and STAC properties.

Created: 17 JAN 2026
Updated: 08 FEB 2026 - V0.8.11 AssetApprovalService refactor
"""

import json
import azure.functions as func

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "ApprovalTriggers")

# V0.8 Entity Architecture imports
from core.models.asset import ClearanceState, ApprovalState


def _resolve_asset_id(
    asset_id: str = None,
    stac_item_id: str = None,
    job_id: str = None,
    request_id: str = None
) -> tuple:
    """
    Resolve asset_id from various B2B identifiers.

    Args:
        asset_id: Direct asset ID
        stac_item_id: STAC item ID
        job_id: Job ID
        request_id: Platform request ID

    Returns:
        Tuple of (asset_id, error_response) - error_response is None if found
    """
    from infrastructure.asset_repository import GeospatialAssetRepository
    asset_repo = GeospatialAssetRepository()

    # Direct asset_id
    if asset_id:
        asset = asset_repo.get_by_id(asset_id)
        if asset:
            return asset.asset_id, None
        return None, {
            "success": False,
            "error": f"Asset not found: {asset_id}",
            "error_type": "NotFound"
        }

    # By STAC item ID
    if stac_item_id:
        asset = asset_repo.get_by_stac_item_id(stac_item_id)
        if asset:
            return asset.asset_id, None
        return None, {
            "success": False,
            "error": f"No asset found for STAC item: {stac_item_id}",
            "error_type": "NotFound"
        }

    # By job ID
    if job_id:
        asset = asset_repo.get_by_job_id(job_id)
        if asset:
            return asset.asset_id, None
        return None, {
            "success": False,
            "error": f"No asset found for job: {job_id}",
            "error_type": "NotFound"
        }

    # By platform request ID
    if request_id:
        from infrastructure import PlatformRepository
        platform_repo = PlatformRepository()
        platform_request = platform_repo.get_request(request_id)
        if not platform_request:
            return None, {
                "success": False,
                "error": f"No platform request found: {request_id}",
                "error_type": "NotFound"
            }
        # Resolve request → job → asset
        asset = asset_repo.get_by_job_id(platform_request.job_id)
        if asset:
            return asset.asset_id, None
        return None, {
            "success": False,
            "error": f"No asset found for request: {request_id} (job: {platform_request.job_id})",
            "error_type": "NotFound"
        }

    # No identifier provided
    return None, {
        "success": False,
        "error": "Must provide asset_id, stac_item_id, job_id, or request_id",
        "error_type": "ValidationError"
    }


def platform_approve(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to approve a pending dataset.

    POST /api/platform/approve

    Approves a dataset for publication. Updates GeospatialAsset.approval_state
    and STAC item with app:published=true. For PUBLIC clearance, triggers ADF.

    Request Body:
    {
        "asset_id": "abc123...",               // Asset ID (preferred)
        "stac_item_id": "my-dataset-v1",       // Or by STAC item
        "job_id": "def456...",                 // Or by job ID
        "request_id": "a3f2c1b8...",           // Or by Platform request ID
        "reviewer": "user@example.com",        // Required: Who is approving
        "clearance_level": "ouo",              // Required: "ouo" or "public"
        "notes": "Looks good"                  // Optional: Review notes
    }

    Clearance Levels:
    - "ouo": Official Use Only - internal access, no external export
    - "public": Public access - triggers ADF pipeline for external zone export

    Response (success):
    {
        "success": true,
        "asset_id": "abc123...",
        "approval_state": "approved",
        "clearance_state": "ouo",
        "action": "approved_ouo",
        "stac_updated": true,
        "adf_run_id": "...",
        "message": "Dataset approved successfully"
    }
    """
    logger.info("Platform approve endpoint called")

    try:
        req_body = req.get_json()

        # Extract identifiers (support multiple lookup methods)
        asset_id_param = req_body.get('asset_id')
        stac_item_id = req_body.get('stac_item_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')
        # Legacy: also accept approval_id as alias for asset_id
        if not asset_id_param:
            asset_id_param = req_body.get('approval_id')

        reviewer = req_body.get('reviewer')
        notes = req_body.get('notes')
        clearance_level_str = req_body.get('clearance_level')

        # Validate reviewer is provided
        if not reviewer:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "reviewer is required",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Validate clearance_level is provided
        if not clearance_level_str:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "clearance_level is required. Must be 'ouo' or 'public'",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Parse clearance level
        try:
            clearance_state = ClearanceState(clearance_level_str.lower())
            if clearance_state == ClearanceState.UNCLEARED:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": "clearance_level must be 'ouo' or 'public', not 'uncleared'",
                        "error_type": "ValidationError"
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )
        except ValueError:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Invalid clearance_level: '{clearance_level_str}'. Must be 'ouo' or 'public'",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Resolve asset_id from various identifiers
        asset_id, error = _resolve_asset_id(
            asset_id=asset_id_param,
            stac_item_id=stac_item_id,
            job_id=job_id,
            request_id=request_id
        )
        if error:
            return func.HttpResponse(
                json.dumps(error),
                status_code=404 if error.get('error_type') == 'NotFound' else 400,
                headers={"Content-Type": "application/json"}
            )

        # Perform approval using AssetApprovalService
        from services.asset_approval_service import AssetApprovalService
        approval_service = AssetApprovalService()

        logger.info(f"Approving asset {asset_id[:16]}... by {reviewer} (clearance: {clearance_state.value})")

        result = approval_service.approve_asset(
            asset_id=asset_id,
            reviewer=reviewer,
            clearance_state=clearance_state,
            notes=notes
        )

        if not result.get('success'):
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": result.get('error'),
                    "error_type": "ApprovalFailed"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        asset_data = result.get('asset', {})

        response_data = {
            "success": True,
            "asset_id": asset_id,
            "approval_state": "approved",
            "clearance_state": clearance_state.value,
            "action": result.get('action', 'approved_ouo'),
            "stac_updated": result.get('stac_updated', False),
            "adf_run_id": result.get('adf_run_id'),
            "stac_item_id": asset_data.get('stac_item_id'),
            "stac_collection_id": asset_data.get('stac_collection_id'),
            "message": "Dataset approved successfully"
        }

        return func.HttpResponse(
            json.dumps(response_data),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except json.JSONDecodeError:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Invalid JSON in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logger.error(f"Platform approve failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def platform_reject(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to reject a pending dataset.

    POST /api/platform/reject

    Rejects a pending dataset that is not suitable for publication.
    Updates GeospatialAsset.approval_state to REJECTED.

    Request Body:
    {
        "asset_id": "abc123...",               // Asset ID (preferred)
        "stac_item_id": "my-dataset-v1",       // Or by STAC item
        "job_id": "def456...",                 // Or by job ID
        "request_id": "a3f2c1b8...",           // Or by Platform request ID
        "reviewer": "user@example.com",        // Required: Who is rejecting
        "reason": "Data quality issue found"   // Required: Reason for rejection
    }

    Response (success):
    {
        "success": true,
        "asset_id": "abc123...",
        "approval_state": "rejected",
        "message": "Dataset rejected"
    }
    """
    logger.info("Platform reject endpoint called")

    try:
        req_body = req.get_json()

        # Extract identifiers
        asset_id_param = req_body.get('asset_id')
        stac_item_id = req_body.get('stac_item_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')
        # Legacy: also accept approval_id as alias for asset_id
        if not asset_id_param:
            asset_id_param = req_body.get('approval_id')

        reviewer = req_body.get('reviewer')
        reason = req_body.get('reason')

        # Validate required fields
        if not reviewer:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "reviewer is required",
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

        # Resolve asset_id
        asset_id, error = _resolve_asset_id(
            asset_id=asset_id_param,
            stac_item_id=stac_item_id,
            job_id=job_id,
            request_id=request_id
        )
        if error:
            return func.HttpResponse(
                json.dumps(error),
                status_code=404 if error.get('error_type') == 'NotFound' else 400,
                headers={"Content-Type": "application/json"}
            )

        # Perform rejection using AssetApprovalService
        from services.asset_approval_service import AssetApprovalService
        approval_service = AssetApprovalService()

        logger.info(f"Rejecting asset {asset_id[:16]}... by {reviewer}. Reason: {reason[:50]}...")

        result = approval_service.reject_asset(
            asset_id=asset_id,
            reviewer=reviewer,
            reason=reason
        )

        if not result.get('success'):
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": result.get('error'),
                    "error_type": "RejectionFailed"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "asset_id": asset_id,
                "approval_state": "rejected",
                "message": "Dataset rejected"
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except json.JSONDecodeError:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Invalid JSON in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logger.error(f"Platform reject failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def platform_revoke(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to revoke an approved dataset (unapprove).

    POST /api/platform/revoke

    Revokes an approved dataset. This is an audit-logged operation for
    when approved data needs to be unpublished. Updates STAC item with
    revocation properties. REVOKED is a terminal state.

    IMPORTANT: This is a necessary but undesirable workflow. All revocations
    are logged with full audit trail.

    Request Body:
    {
        "asset_id": "abc123...",               // Asset ID (preferred)
        "stac_item_id": "my-dataset-v1",       // Or by STAC item
        "job_id": "def456...",                 // Or by job ID
        "request_id": "a3f2c1b8...",           // Or by Platform request ID
        "revoker": "user@example.com",         // Required: Who is revoking
        "reason": "Data quality issue found"   // Required: Reason for revocation
    }

    Response (success):
    {
        "success": true,
        "asset_id": "abc123...",
        "approval_state": "revoked",
        "stac_updated": true,
        "warning": "Approved dataset has been revoked - this action is logged for audit",
        "message": "Approval revoked successfully"
    }
    """
    logger.info("Platform revoke endpoint called")

    try:
        req_body = req.get_json()

        # Extract identifiers
        asset_id_param = req_body.get('asset_id')
        stac_item_id = req_body.get('stac_item_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')
        # Legacy: also accept approval_id as alias for asset_id
        if not asset_id_param:
            asset_id_param = req_body.get('approval_id')

        revoker = req_body.get('revoker')
        reason = req_body.get('reason')

        # Validate required fields
        if not revoker:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "revoker is required",
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

        # Resolve asset_id
        asset_id, error = _resolve_asset_id(
            asset_id=asset_id_param,
            stac_item_id=stac_item_id,
            job_id=job_id,
            request_id=request_id
        )
        if error:
            return func.HttpResponse(
                json.dumps(error),
                status_code=404 if error.get('error_type') == 'NotFound' else 400,
                headers={"Content-Type": "application/json"}
            )

        # Perform revocation using AssetApprovalService
        from services.asset_approval_service import AssetApprovalService
        approval_service = AssetApprovalService()

        logger.warning(f"AUDIT: Revoking asset {asset_id[:16]}... by {revoker}. Reason: {reason}")

        result = approval_service.revoke_asset(
            asset_id=asset_id,
            revoker=revoker,
            reason=reason
        )

        if not result.get('success'):
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": result.get('error'),
                    "error_type": "RevocationFailed"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "asset_id": asset_id,
                "approval_state": "revoked",
                "stac_updated": result.get('stac_updated', False),
                "warning": result.get('warning'),
                "message": "Approval revoked successfully"
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except json.JSONDecodeError:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Invalid JSON in request body",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logger.error(f"Platform revoke failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def platform_approvals_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to list assets by approval state.

    GET /api/platform/approvals

    Query Parameters:
        status: Filter by approval_state (pending_review, approved, rejected, revoked)
        clearance: Filter by clearance_state (uncleared, ouo, public)
        limit: Max results (default 100)
        offset: Pagination offset (default 0)

    Response:
    {
        "success": true,
        "assets": [...],
        "count": 25,
        "limit": 100,
        "offset": 0,
        "status_counts": {
            "pending_review": 5,
            "approved": 15,
            "rejected": 3,
            "revoked": 2
        }
    }
    """
    logger.info("Platform approvals list endpoint called")

    try:
        # Extract query parameters
        status_filter = req.params.get('status')
        clearance_filter = req.params.get('clearance')
        limit = int(req.params.get('limit', 100))
        offset = int(req.params.get('offset', 0))

        # Import service
        from services.asset_approval_service import AssetApprovalService
        approval_service = AssetApprovalService()

        # Parse status filter
        approval_state = None
        if status_filter:
            # Normalize status names (legacy used "pending", new uses "pending_review")
            status_map = {
                'pending': 'pending_review',
                'pending_review': 'pending_review',
                'approved': 'approved',
                'rejected': 'rejected',
                'revoked': 'revoked'
            }
            normalized = status_map.get(status_filter.lower())
            if not normalized:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Invalid status: {status_filter}. Valid values: pending_review, approved, rejected, revoked",
                        "error_type": "ValidationError"
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )
            try:
                approval_state = ApprovalState(normalized)
            except ValueError:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Invalid status: {status_filter}",
                        "error_type": "ValidationError"
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )

        # Fetch assets
        if approval_state:
            assets = approval_service.list_by_approval_state(
                approval_state=approval_state,
                limit=limit
            )
        else:
            # Default: list pending review
            assets = approval_service.list_pending_review(limit=limit)

        # Get status counts
        status_counts = approval_service.get_approval_stats()

        # Convert to JSON-serializable format
        assets_data = []
        for asset in assets:
            asset_dict = asset.to_dict()
            assets_data.append(asset_dict)

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "assets": assets_data,
                "count": len(assets_data),
                "limit": limit,
                "offset": offset,
                "status_counts": status_counts
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform approvals list failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def platform_approval_get(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to get a single asset's approval state.

    GET /api/platform/approvals/{asset_id}

    Also accepts approval_id for backwards compatibility (resolved as asset_id).

    Response:
    {
        "success": true,
        "asset": {...}
    }
    """
    logger.info("Platform approval get endpoint called")

    try:
        # Get asset_id from route (may be labeled as approval_id in legacy routes)
        asset_id = req.route_params.get('approval_id') or req.route_params.get('asset_id')

        if not asset_id:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "asset_id is required",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Get asset
        from infrastructure.asset_repository import GeospatialAssetRepository
        asset_repo = GeospatialAssetRepository()

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

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "asset": asset.to_dict()
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform approval get failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def platform_approvals_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to get approval statuses for multiple STAC items/collections.

    GET /api/platform/approvals/status?stac_item_ids=item1,item2,item3
    GET /api/platform/approvals/status?stac_collection_ids=col1,col2

    Returns a map of ID -> approval status for quick UI lookups.

    Query Parameters:
        stac_item_ids: Comma-separated list of STAC item IDs
        stac_collection_ids: Comma-separated list of STAC collection IDs
        table_names: Comma-separated list of table names (for OGC Features)

    Response:
    {
        "success": true,
        "statuses": {
            "item1": {
                "has_asset": true,
                "asset_id": "abc123",
                "approval_state": "approved",
                "is_approved": true,
                "reviewer": "user@example.com",
                "reviewed_at": "2026-01-17T..."
            },
            "item2": {
                "has_asset": false
            }
        }
    }
    """
    logger.info("Platform approvals status endpoint called")

    try:
        # Get query parameters
        stac_item_ids_param = req.params.get('stac_item_ids', '')
        stac_collection_ids_param = req.params.get('stac_collection_ids', '')
        table_names_param = req.params.get('table_names', '')

        # Parse comma-separated IDs
        stac_item_ids = [id.strip() for id in stac_item_ids_param.split(',') if id.strip()]
        stac_collection_ids = [id.strip() for id in stac_collection_ids_param.split(',') if id.strip()]
        table_names = [name.strip() for name in table_names_param.split(',') if name.strip()]

        if not stac_item_ids and not stac_collection_ids and not table_names:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Must provide stac_item_ids, stac_collection_ids, or table_names query parameter",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        from infrastructure.asset_repository import GeospatialAssetRepository
        asset_repo = GeospatialAssetRepository()

        statuses = {}

        # Look up by STAC item IDs
        for item_id in stac_item_ids:
            asset = asset_repo.get_by_stac_item_id(item_id)
            if asset:
                is_approved = asset.approval_state == ApprovalState.APPROVED
                statuses[item_id] = {
                    "has_asset": True,
                    "asset_id": asset.asset_id,
                    "approval_state": asset.approval_state.value if asset.approval_state else None,
                    "is_approved": is_approved,
                    "clearance_state": asset.clearance_state.value if asset.clearance_state else None,
                    "reviewer": asset.reviewer,
                    "reviewed_at": asset.reviewed_at.isoformat() if asset.reviewed_at else None
                }
            else:
                statuses[item_id] = {"has_asset": False}

        # Look up by STAC collection IDs
        # For collections, we check assets with matching stac_collection_id
        for collection_id in stac_collection_ids:
            assets = asset_repo.list_by_stac_collection(collection_id) if hasattr(asset_repo, 'list_by_stac_collection') else []
            if assets:
                approved_count = sum(1 for a in assets if a.approval_state == ApprovalState.APPROVED)
                any_approved = approved_count > 0
                statuses[collection_id] = {
                    "has_asset": True,
                    "asset_count": len(assets),
                    "approved_count": approved_count,
                    "is_approved": any_approved,
                    "approval_state": "approved" if any_approved else (assets[0].approval_state.value if assets[0].approval_state else None)
                }
            else:
                statuses[collection_id] = {"has_asset": False}

        # Look up by table names (for OGC Features / vector tables)
        if table_names:
            try:
                from infrastructure.postgresql import PostgreSQLRepository
                repo = PostgreSQLRepository()

                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        for table_name in table_names:
                            cur.execute(
                                """
                                SELECT stac_item_id, stac_collection_id
                                FROM geo.table_catalog
                                WHERE table_name = %s
                                """,
                                (table_name,)
                            )
                            row = cur.fetchone()

                            if row and row.get('stac_item_id'):
                                stac_item_id = row['stac_item_id']
                                asset = asset_repo.get_by_stac_item_id(stac_item_id)

                                if asset:
                                    is_approved = asset.approval_state == ApprovalState.APPROVED
                                    statuses[table_name] = {
                                        "has_asset": True,
                                        "asset_id": asset.asset_id,
                                        "approval_state": asset.approval_state.value if asset.approval_state else None,
                                        "is_approved": is_approved,
                                        "stac_item_id": stac_item_id,
                                        "reviewer": asset.reviewer,
                                        "reviewed_at": asset.reviewed_at.isoformat() if asset.reviewed_at else None
                                    }
                                else:
                                    statuses[table_name] = {
                                        "has_asset": False,
                                        "stac_item_id": stac_item_id
                                    }
                            else:
                                statuses[table_name] = {"has_asset": False, "no_stac_item": True}
            except Exception as e:
                logger.warning(f"Error looking up table approvals: {e}")
                for table_name in table_names:
                    if table_name not in statuses:
                        statuses[table_name] = {"has_asset": False, "error": str(e)}

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "statuses": statuses
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform approvals status failed: {e}", exc_info=True)
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
__all__ = [
    'platform_approve',
    'platform_reject',
    'platform_revoke',
    'platform_approvals_list',
    'platform_approval_get',
    'platform_approvals_status'
]
