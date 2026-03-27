"""
Assets API for DAG Brain Admin UI.

Direct service calls — no proxy to Function App.

Endpoints:
    GET  /ui/api/assets/stats              - Approval state counts
    GET  /ui/api/assets/by-state           - List releases by approval state
    GET  /ui/api/assets/{asset_id}         - Single asset with releases
    POST /ui/api/assets/{asset_id}/approve - Approve a release
    POST /ui/api/assets/{asset_id}/reject  - Reject a release
    POST /ui/api/assets/{asset_id}/revoke  - Revoke an approval
"""
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.asset_approval_service import AssetApprovalService
from infrastructure.asset_repository import AssetRepository
from infrastructure.release_repository import ReleaseRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api/assets", tags=["assets"])


@router.get("/stats")
async def approval_stats():
    """GET /ui/api/assets/stats — approval state counts."""
    try:
        service = AssetApprovalService()
        stats = service.get_approval_stats()
        total = sum(stats.values())
        return JSONResponse(content={"success": True, "stats": stats, "total": total})
    except Exception as e:
        logger.warning(f"Assets stats failed: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@router.get("/by-state")
async def list_by_state(state: str = "pending_review", limit: int = 100):
    """GET /ui/api/assets/by-state — list releases by approval state."""
    try:
        from core.models.asset import ApprovalState
        try:
            approval_state = ApprovalState(state.lower())
        except ValueError:
            return JSONResponse(
                content={
                    "success": False,
                    "error": f"Invalid state: '{state}'. Valid values: pending_review, approved, rejected, revoked",
                    "error_type": "ValidationError",
                },
                status_code=400,
            )

        release_repo = ReleaseRepository()
        releases = release_repo.list_by_approval_state(state=approval_state, limit=limit)

        return JSONResponse(
            content=json.loads(
                json.dumps(
                    {
                        "success": True,
                        "releases": [r.to_dict() for r in releases],
                        "count": len(releases),
                        "state": state,
                        "limit": limit,
                    },
                    default=str,
                )
            )
        )
    except Exception as e:
        logger.warning(f"Assets by-state failed: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@router.get("/{asset_id}")
async def get_asset(asset_id: str):
    """GET /ui/api/assets/{asset_id} — single asset with releases."""
    try:
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(asset_id)
        if not asset:
            return JSONResponse(
                content={
                    "success": False,
                    "error": f"Asset not found: {asset_id}",
                    "error_type": "NotFound",
                },
                status_code=404,
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

        return JSONResponse(
            content=json.loads(json.dumps(response_data, default=str))
        )
    except Exception as e:
        logger.warning(f"Asset detail failed: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@router.post("/{asset_id}/approve")
async def approve_asset(asset_id: str, request: Request):
    """POST /ui/api/assets/{asset_id}/approve — approve a release."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"success": False, "error": "Invalid JSON in request body", "error_type": "ValidationError"},
            status_code=400,
        )

    reviewer = body.get("reviewer")
    clearance_state_str = body.get("clearance_state", "ouo")
    version_id = body.get("version_id")
    notes = body.get("notes")

    if not reviewer:
        return JSONResponse(
            content={"success": False, "error": "reviewer is required", "error_type": "ValidationError"},
            status_code=400,
        )

    try:
        from core.models.asset import ClearanceState
        clearance_state = ClearanceState(clearance_state_str.lower())
        if clearance_state == ClearanceState.UNCLEARED:
            return JSONResponse(
                content={
                    "success": False,
                    "error": "clearance_state must be 'ouo' or 'public', not 'uncleared'",
                    "error_type": "ValidationError",
                },
                status_code=400,
            )
    except ValueError:
        return JSONResponse(
            content={
                "success": False,
                "error": f"Invalid clearance_state: '{clearance_state_str}'. Must be 'ouo' or 'public'",
                "error_type": "ValidationError",
            },
            status_code=400,
        )

    try:
        release_repo = ReleaseRepository()
        release = release_repo.get_draft(asset_id)
        if not release:
            release = release_repo.get_latest(asset_id)
        if not release:
            return JSONResponse(
                content={
                    "success": False,
                    "error": f"No release found for asset {asset_id}",
                    "error_type": "NotFound",
                },
                status_code=404,
            )

        # Auto-generate version_id from ordinal if not provided
        if not version_id and release.version_ordinal:
            version_id = f"v{release.version_ordinal}"
        elif not version_id:
            version_id = "v1"

        service = AssetApprovalService()
        result = service.approve_release(
            release_id=release.release_id,
            reviewer=reviewer,
            clearance_state=clearance_state,
            version_id=version_id,
            notes=notes,
        )

        status = 200 if result.get("success") else 409
        return JSONResponse(
            content=json.loads(json.dumps(result, default=str)),
            status_code=status,
        )
    except Exception as e:
        logger.warning(f"Approve failed: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@router.post("/{asset_id}/reject")
async def reject_asset(asset_id: str, request: Request):
    """POST /ui/api/assets/{asset_id}/reject — reject a release."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"success": False, "error": "Invalid JSON in request body", "error_type": "ValidationError"},
            status_code=400,
        )

    reviewer = body.get("reviewer")
    reason = body.get("reason")

    if not reviewer:
        return JSONResponse(
            content={"success": False, "error": "reviewer is required", "error_type": "ValidationError"},
            status_code=400,
        )
    if not reason or not reason.strip():
        return JSONResponse(
            content={"success": False, "error": "reason is required for audit trail", "error_type": "ValidationError"},
            status_code=400,
        )

    try:
        release_repo = ReleaseRepository()
        release = release_repo.get_draft(asset_id)
        if not release:
            release = release_repo.get_latest(asset_id)
        if not release:
            return JSONResponse(
                content={
                    "success": False,
                    "error": f"No release found for asset {asset_id}",
                    "error_type": "NotFound",
                },
                status_code=404,
            )

        service = AssetApprovalService()
        result = service.reject_release(
            release_id=release.release_id,
            reviewer=reviewer,
            reason=reason,
        )

        status = 200 if result.get("success") else 409
        return JSONResponse(
            content=json.loads(json.dumps(result, default=str)),
            status_code=status,
        )
    except Exception as e:
        logger.warning(f"Reject failed: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@router.post("/{asset_id}/revoke")
async def revoke_asset(asset_id: str, request: Request):
    """POST /ui/api/assets/{asset_id}/revoke — revoke an approved release."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"success": False, "error": "Invalid JSON in request body", "error_type": "ValidationError"},
            status_code=400,
        )

    # Accept both 'reviewer' and 'revoker' for actor field
    reviewer = body.get("reviewer") or body.get("revoker")
    reason = body.get("reason")

    if not reviewer:
        return JSONResponse(
            content={"success": False, "error": "reviewer is required", "error_type": "ValidationError"},
            status_code=400,
        )
    if not reason or not reason.strip():
        return JSONResponse(
            content={"success": False, "error": "reason is required for audit trail", "error_type": "ValidationError"},
            status_code=400,
        )

    try:
        release_repo = ReleaseRepository()
        release = release_repo.get_latest(asset_id)  # revoke targets latest approved release
        if not release:
            return JSONResponse(
                content={
                    "success": False,
                    "error": f"No approved release found for asset {asset_id}",
                    "error_type": "NotFound",
                },
                status_code=404,
            )

        service = AssetApprovalService()
        result = service.revoke_release(
            release_id=release.release_id,
            revoker=reviewer,
            reason=reason,
        )

        status = 200 if result.get("success") else 409
        return JSONResponse(
            content=json.loads(json.dumps(result, default=str)),
            status_code=status,
        )
    except Exception as e:
        logger.warning(f"Revoke failed: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)
