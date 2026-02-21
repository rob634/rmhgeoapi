# ============================================================================
# APPROVAL PLATFORM TRIGGERS (V0.9 - RELEASE-BASED)
# ============================================================================
# STATUS: Trigger - HTTP endpoints for dataset approval workflow
# PURPOSE: Platform API for approving and revoking dataset approvals
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: platform_approve, platform_reject, platform_revoke, platform_approvals_list
# DEPENDENCIES: services.asset_approval_service, infrastructure.release_repository
# ============================================================================
"""
Approval Platform Triggers (V0.9 Release-Based).

HTTP endpoints for the dataset approval workflow:
- POST /api/platform/approve - Approve a pending release
- POST /api/platform/reject - Reject a pending release
- POST /api/platform/revoke - Revoke an approved release (unapprove)
- GET /api/platform/approvals - List releases with approval filters
- GET /api/platform/approvals/{id} - Get a single release's approval state
- GET /api/platform/approvals/status - Bulk status lookup by STAC IDs

V0.9 Refactor (21 FEB 2026):
- Approval targets AssetRelease, NOT Asset
- Uses AssetApprovalService (release-centric)
- Replaces 3-tier asset_id fallback with simplified _resolve_release()
- Version assignment handled internally by approve_release()
- Response includes release_id as the primary identifier

These are synchronous operations (no async jobs) since they're simple
state changes to approval records and STAC properties.

Created: 17 JAN 2026
Updated: 21 FEB 2026 - V0.9 Release-based approval
"""

import json
import azure.functions as func

from triggers.http_base import parse_request_json
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "ApprovalTriggers")

# V0.9 Entity Architecture imports
from core.models.asset import ClearanceState, ApprovalState


def _resolve_release(
    release_id: str = None,
    asset_id: str = None,
    job_id: str = None,
    request_id: str = None,
    dataset_id: str = None,
    resource_id: str = None
) -> tuple:
    """
    Resolve an AssetRelease from various identifiers.

    V0.9 simplified resolution -- no 3-tier fallback, no JSONB containment
    queries. Each lookup path is a direct FK or indexed column on the
    asset_releases table.

    Resolution order:
        1. release_id (primary path -- preferred)
        2. job_id (direct FK on Release)
        3. request_id (stored on Release)
        4. asset_id (get draft first, then latest approved)
        5. dataset_id + resource_id (find Asset first, then Release)

    Args:
        release_id: Direct release identifier (preferred)
        asset_id: Asset identifier (finds latest draft or approved release)
        job_id: Processing job identifier
        request_id: Platform request identifier
        dataset_id: DDH dataset identifier (must be paired with resource_id)
        resource_id: DDH resource identifier (must be paired with dataset_id)

    Returns:
        Tuple of (AssetRelease, error_dict) - error_dict is None if found
    """
    from infrastructure import ReleaseRepository, AssetRepository
    release_repo = ReleaseRepository()

    # 1. Direct release_id (primary path)
    if release_id:
        release = release_repo.get_by_id(release_id)
        if release:
            return release, None
        return None, {
            "success": False,
            "error": f"Release not found: {release_id}",
            "error_type": "NotFound"
        }

    # 2. By job_id -- direct FK on Release
    if job_id:
        release = release_repo.get_by_job_id(job_id)
        if release:
            return release, None
        return None, {
            "success": False,
            "error": f"No release found for job: {job_id}",
            "error_type": "NotFound"
        }

    # 3. By request_id -- stored on Release
    if request_id:
        release = release_repo.get_by_request_id(request_id)
        if release:
            return release, None
        return None, {
            "success": False,
            "error": f"No release found for request: {request_id}",
            "error_type": "NotFound"
        }

    # 4. By asset_id -- get draft first (for approve/reject), then latest approved (for revoke)
    if asset_id:
        release = release_repo.get_draft(asset_id)
        if not release:
            release = release_repo.get_latest(asset_id)
        if release:
            return release, None
        return None, {
            "success": False,
            "error": f"No release found for asset: {asset_id}",
            "error_type": "NotFound"
        }

    # 5. By dataset_id + resource_id -- find asset first, then release
    if dataset_id and resource_id:
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_identity("ddh", dataset_id, resource_id)
        if asset:
            release = release_repo.get_draft(asset.asset_id)
            if not release:
                release = release_repo.get_latest(asset.asset_id)
            if release:
                return release, None
        return None, {
            "success": False,
            "error": f"No release found for dataset_id={dataset_id}, resource_id={resource_id}",
            "error_type": "NotFound"
        }

    # No identifier provided
    return None, {
        "success": False,
        "error": "Must provide release_id, asset_id, job_id, request_id, or dataset_id+resource_id",
        "error_type": "ValidationError"
    }


def platform_approve(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to approve a pending release.

    POST /api/platform/approve

    Approves a release for publication. Updates AssetRelease approval_state
    and materializes STAC item from cached stac_item_json. For PUBLIC
    clearance, triggers ADF pipeline.

    V0.9: Version assignment is handled internally by approve_release() --
    the caller provides version_id but does NOT need to call assign_version().

    Request Body:
    {
        "release_id": "abc123...",             // Release ID (preferred)
        "asset_id": "def456...",               // Or by asset ID (finds draft/latest)
        "job_id": "ghi789...",                 // Or by job ID
        "request_id": "a3f2c1b8...",           // Or by Platform request ID
        "dataset_id": "floods",                // Or by dataset+resource
        "resource_id": "jakarta",
        "reviewer": "user@example.com",        // Required: Who is approving
        "clearance_level": "ouo",              // Required: "ouo" or "public"
        "version_id": "v1",                    // Required: Version to assign
        "notes": "Looks good"                  // Optional: Review notes
    }

    Response (success):
    {
        "success": true,
        "release_id": "abc123...",
        "asset_id": "def456...",
        "approval_state": "approved",
        "clearance_state": "ouo",
        "action": "approved_ouo",
        "stac_updated": true,
        "adf_run_id": "...",
        "message": "Release approved successfully"
    }
    """
    logger.info("Platform approve endpoint called")

    try:
        req_body = parse_request_json(req)

        # Extract identifiers (support multiple lookup methods)
        release_id_param = req_body.get('release_id')
        asset_id_param = req_body.get('asset_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')
        dataset_id = req_body.get('dataset_id')
        resource_id = req_body.get('resource_id')
        # Legacy: also accept approval_id as alias for asset_id
        if not asset_id_param:
            asset_id_param = req_body.get('approval_id')

        reviewer = req_body.get('reviewer')
        notes = req_body.get('notes')
        clearance_level_str = req_body.get('clearance_level')
        version_id = req_body.get('version_id')

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

        # Validate version_id is provided
        if not version_id:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "version_id is required (e.g., 'v1', 'v2')",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Resolve release from various identifiers
        release, error = _resolve_release(
            release_id=release_id_param,
            asset_id=asset_id_param,
            job_id=job_id,
            request_id=request_id,
            dataset_id=dataset_id,
            resource_id=resource_id
        )
        if error:
            status_code = 404 if error.get('error_type') == 'NotFound' else 400
            return func.HttpResponse(
                json.dumps(error),
                status_code=status_code,
                headers={"Content-Type": "application/json"}
            )

        # V0.9: Approve release (version assignment handled internally)
        from services.asset_approval_service import AssetApprovalService
        approval_service = AssetApprovalService()

        logger.info(
            f"Approving release {release.release_id[:16]}... by {reviewer} "
            f"(clearance: {clearance_state.value}, version: {version_id})"
        )

        result = approval_service.approve_release(
            release_id=release.release_id,
            reviewer=reviewer,
            clearance_state=clearance_state,
            version_id=version_id,
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

        release_data = result.get('release', {})

        response_data = {
            "success": True,
            "release_id": release.release_id,
            "asset_id": release.asset_id,
            "approval_state": "approved",
            "clearance_state": clearance_state.value,
            "action": result.get('action', 'approved_ouo'),
            "stac_updated": result.get('stac_updated', False),
            "adf_run_id": result.get('adf_run_id'),
            "stac_item_id": release_data.get('stac_item_id') if isinstance(release_data, dict) else None,
            "stac_collection_id": release_data.get('stac_collection_id') if isinstance(release_data, dict) else None,
            "version_id": version_id,
            "message": "Release approved successfully"
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
    HTTP trigger to reject a pending release.

    POST /api/platform/reject

    Rejects a pending release that is not suitable for publication.
    Updates AssetRelease.approval_state to REJECTED.

    Request Body:
    {
        "release_id": "abc123...",             // Release ID (preferred)
        "asset_id": "def456...",               // Or by asset ID
        "job_id": "ghi789...",                 // Or by job ID
        "request_id": "a3f2c1b8...",           // Or by Platform request ID
        "dataset_id": "floods",                // Or by dataset+resource
        "resource_id": "jakarta",
        "reviewer": "user@example.com",        // Required: Who is rejecting
        "reason": "Data quality issue found"   // Required: Reason for rejection
    }

    Response (success):
    {
        "success": true,
        "release_id": "abc123...",
        "asset_id": "def456...",
        "approval_state": "rejected",
        "message": "Release rejected"
    }
    """
    logger.info("Platform reject endpoint called")

    try:
        req_body = parse_request_json(req)

        # Extract identifiers
        release_id_param = req_body.get('release_id')
        asset_id_param = req_body.get('asset_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')
        dataset_id = req_body.get('dataset_id')
        resource_id = req_body.get('resource_id')
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

        # Resolve release
        release, error = _resolve_release(
            release_id=release_id_param,
            asset_id=asset_id_param,
            job_id=job_id,
            request_id=request_id,
            dataset_id=dataset_id,
            resource_id=resource_id
        )
        if error:
            status_code = 404 if error.get('error_type') == 'NotFound' else 400
            return func.HttpResponse(
                json.dumps(error),
                status_code=status_code,
                headers={"Content-Type": "application/json"}
            )

        # Perform rejection using AssetApprovalService
        from services.asset_approval_service import AssetApprovalService
        approval_service = AssetApprovalService()

        logger.info(f"Rejecting release {release.release_id[:16]}... by {reviewer}. Reason: {reason[:50]}...")

        result = approval_service.reject_release(
            release_id=release.release_id,
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
                "release_id": release.release_id,
                "asset_id": release.asset_id,
                "approval_state": "rejected",
                "message": "Release rejected"
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
    HTTP trigger to revoke an approved release (unapprove).

    POST /api/platform/revoke

    Revokes an approved release. This is an audit-logged operation for
    when approved data needs to be unpublished. STAC item is deleted from
    pgSTAC. REVOKED is a terminal state -- to re-publish, submit a new version.

    Request Body:
    {
        "release_id": "abc123...",             // Release ID (preferred)
        "asset_id": "def456...",               // Or by asset ID
        "job_id": "ghi789...",                 // Or by job ID
        "request_id": "a3f2c1b8...",           // Or by Platform request ID
        "dataset_id": "floods",                // Or by dataset+resource
        "resource_id": "jakarta",
        "revoker": "user@example.com",         // Required: Who is revoking
        "reason": "Data quality issue found"   // Required: Reason for revocation
    }

    Response (success):
    {
        "success": true,
        "release_id": "abc123...",
        "asset_id": "def456...",
        "approval_state": "revoked",
        "stac_updated": true,
        "warning": "Approved release has been revoked...",
        "message": "Approval revoked successfully"
    }
    """
    logger.info("Platform revoke endpoint called")

    try:
        req_body = parse_request_json(req)

        # Extract identifiers
        release_id_param = req_body.get('release_id')
        asset_id_param = req_body.get('asset_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')
        dataset_id = req_body.get('dataset_id')
        resource_id = req_body.get('resource_id')
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

        # Resolve release
        release, error = _resolve_release(
            release_id=release_id_param,
            asset_id=asset_id_param,
            job_id=job_id,
            request_id=request_id,
            dataset_id=dataset_id,
            resource_id=resource_id
        )
        if error:
            status_code = 404 if error.get('error_type') == 'NotFound' else 400
            return func.HttpResponse(
                json.dumps(error),
                status_code=status_code,
                headers={"Content-Type": "application/json"}
            )

        # Perform revocation using AssetApprovalService
        from services.asset_approval_service import AssetApprovalService
        approval_service = AssetApprovalService()

        logger.warning(f"AUDIT: Revoking release {release.release_id[:16]}... by {revoker}. Reason: {reason}")

        result = approval_service.revoke_release(
            release_id=release.release_id,
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
                "release_id": release.release_id,
                "asset_id": release.asset_id,
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
    HTTP trigger to list releases by approval state.

    GET /api/platform/approvals

    V0.9: Returns releases, not assets. Response key is "releases".

    Query Parameters:
        status: Filter by approval_state (pending_review, approved, rejected, revoked)
        clearance: Filter by clearance_state (uncleared, ouo, public)
        limit: Max results (default 100)
        offset: Pagination offset (default 0)

    Response:
    {
        "success": true,
        "releases": [...],
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
        limit = int(req.params.get('limit', 100))
        offset = int(req.params.get('offset', 0))

        # Import V0.9 service
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

        # Fetch releases
        if approval_state:
            from infrastructure import ReleaseRepository
            release_repo = ReleaseRepository()
            releases = release_repo.list_by_approval_state(
                state=approval_state,
                limit=limit
            )
        else:
            # Default: list pending review (completed + pending_review)
            releases = approval_service.list_pending_review(limit=limit)

        # Get status counts
        status_counts = approval_service.get_approval_stats()

        # Convert to JSON-serializable format
        releases_data = []
        for release in releases:
            release_dict = release.to_dict()
            releases_data.append(release_dict)

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "releases": releases_data,
                "count": len(releases_data),
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
    HTTP trigger to get a single release's approval state.

    GET /api/platform/approvals/{release_id}

    Also accepts asset_id or approval_id for backwards compatibility
    (resolved to the latest release for that asset).

    Response:
    {
        "success": true,
        "release": {...}
    }
    """
    logger.info("Platform approval get endpoint called")

    try:
        # Get identifier from route (may be labeled as approval_id, asset_id, or release_id)
        identifier = (
            req.route_params.get('release_id')
            or req.route_params.get('approval_id')
            or req.route_params.get('asset_id')
        )

        if not identifier:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "release_id or asset_id is required",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        from infrastructure import ReleaseRepository
        release_repo = ReleaseRepository()

        # Try as release_id first
        release = release_repo.get_by_id(identifier)

        if not release:
            # Try as asset_id -- get draft first, then latest
            release = release_repo.get_draft(identifier)
            if not release:
                release = release_repo.get_latest(identifier)

        if not release:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Release not found: {identifier}",
                    "error_type": "NotFound"
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "release": release.to_dict()
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

    V0.9: Queries releases (asset_releases table) instead of assets.
    Returns release-centric status with release_id.

    Query Parameters:
        stac_item_ids: Comma-separated list of STAC item IDs
        stac_collection_ids: Comma-separated list of STAC collection IDs
        table_names: Comma-separated list of table names (for OGC Features)

    Response:
    {
        "success": true,
        "statuses": {
            "item1": {
                "has_release": true,
                "release_id": "abc123",
                "asset_id": "def456",
                "approval_state": "approved",
                "is_approved": true,
                "reviewer": "user@example.com",
                "reviewed_at": "2026-02-17T..."
            },
            "item2": {
                "has_release": false
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

        from infrastructure import ReleaseRepository
        release_repo = ReleaseRepository()

        statuses = {}

        # Look up by STAC item IDs -- query releases by stac_item_id
        if stac_item_ids:
            _lookup_releases_by_stac_item_ids(release_repo, stac_item_ids, statuses)

        # Look up by STAC collection IDs -- query releases by stac_collection_id
        if stac_collection_ids:
            _lookup_releases_by_stac_collection_ids(release_repo, stac_collection_ids, statuses)

        # Look up by table names (for OGC Features / vector tables)
        if table_names:
            _lookup_releases_by_table_names(release_repo, table_names, statuses)

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


# =============================================================================
# INTERNAL HELPERS for platform_approvals_status
# =============================================================================

def _lookup_releases_by_stac_item_ids(release_repo, stac_item_ids, statuses):
    """
    Query asset_releases by stac_item_id for bulk status lookup.

    Uses a single SQL query with IN clause for efficiency instead of
    N+1 individual lookups.
    """
    from psycopg import sql as psql

    try:
        with release_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    psql.SQL("""
                        SELECT stac_item_id, release_id, asset_id, approval_state,
                               clearance_state, reviewer, reviewed_at, version_id
                        FROM {}.{}
                        WHERE stac_item_id = ANY(%s)
                        ORDER BY created_at DESC
                    """).format(
                        psql.Identifier(release_repo.schema),
                        psql.Identifier(release_repo.table)
                    ),
                    (stac_item_ids,)
                )
                rows = cur.fetchall()

        # Group by stac_item_id, take the first (newest) release
        seen = set()
        for row in rows:
            item_id = row['stac_item_id']
            if item_id in seen:
                continue
            seen.add(item_id)

            is_approved = row['approval_state'] == ApprovalState.APPROVED.value
            statuses[item_id] = {
                "has_release": True,
                "release_id": row['release_id'],
                "asset_id": row['asset_id'],
                "approval_state": row['approval_state'],
                "is_approved": is_approved,
                "clearance_state": row.get('clearance_state'),
                "reviewer": row.get('reviewer'),
                "reviewed_at": row['reviewed_at'].isoformat() if row.get('reviewed_at') else None,
                "version_id": row.get('version_id')
            }

        # Mark missing items
        for item_id in stac_item_ids:
            if item_id not in statuses:
                statuses[item_id] = {"has_release": False}

    except Exception as e:
        logger.warning(f"Error looking up releases by stac_item_ids: {e}")
        for item_id in stac_item_ids:
            if item_id not in statuses:
                statuses[item_id] = {"has_release": False, "error": str(e)}


def _lookup_releases_by_stac_collection_ids(release_repo, stac_collection_ids, statuses):
    """
    Query asset_releases by stac_collection_id for bulk status lookup.

    For collections, we report aggregate stats: total releases, approved count.
    """
    from psycopg import sql as psql

    try:
        with release_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    psql.SQL("""
                        SELECT stac_collection_id,
                               COUNT(*) as total_count,
                               COUNT(*) FILTER (WHERE approval_state = %s) as approved_count
                        FROM {}.{}
                        WHERE stac_collection_id = ANY(%s)
                        GROUP BY stac_collection_id
                    """).format(
                        psql.Identifier(release_repo.schema),
                        psql.Identifier(release_repo.table)
                    ),
                    (ApprovalState.APPROVED.value, stac_collection_ids)
                )
                rows = cur.fetchall()

        for row in rows:
            collection_id = row['stac_collection_id']
            approved_count = row['approved_count']
            any_approved = approved_count > 0
            statuses[collection_id] = {
                "has_release": True,
                "release_count": row['total_count'],
                "approved_count": approved_count,
                "is_approved": any_approved,
                "approval_state": "approved" if any_approved else "pending_review"
            }

        # Mark missing collections
        for collection_id in stac_collection_ids:
            if collection_id not in statuses:
                statuses[collection_id] = {"has_release": False}

    except Exception as e:
        logger.warning(f"Error looking up releases by stac_collection_ids: {e}")
        for collection_id in stac_collection_ids:
            if collection_id not in statuses:
                statuses[collection_id] = {"has_release": False, "error": str(e)}


def _lookup_releases_by_table_names(release_repo, table_names, statuses):
    """
    Look up releases by OGC Features table names.

    First resolves table_name -> stac_item_id via geo.table_catalog,
    then looks up the release by stac_item_id.
    """
    from psycopg import sql as psql

    try:
        with release_repo._get_connection() as conn:
            with conn.cursor() as cur:
                for table_name in table_names:
                    # Resolve table_name -> stac_item_id from table_catalog
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

                        # Query release by stac_item_id
                        cur.execute(
                            psql.SQL("""
                                SELECT release_id, asset_id, approval_state,
                                       reviewer, reviewed_at, version_id
                                FROM {}.{}
                                WHERE stac_item_id = %s
                                ORDER BY created_at DESC
                                LIMIT 1
                            """).format(
                                psql.Identifier(release_repo.schema),
                                psql.Identifier(release_repo.table)
                            ),
                            (stac_item_id,)
                        )
                        release_row = cur.fetchone()

                        if release_row:
                            is_approved = release_row['approval_state'] == ApprovalState.APPROVED.value
                            statuses[table_name] = {
                                "has_release": True,
                                "release_id": release_row['release_id'],
                                "asset_id": release_row['asset_id'],
                                "approval_state": release_row['approval_state'],
                                "is_approved": is_approved,
                                "stac_item_id": stac_item_id,
                                "reviewer": release_row.get('reviewer'),
                                "reviewed_at": release_row['reviewed_at'].isoformat() if release_row.get('reviewed_at') else None
                            }
                        else:
                            statuses[table_name] = {
                                "has_release": False,
                                "stac_item_id": stac_item_id
                            }
                    else:
                        statuses[table_name] = {"has_release": False, "no_stac_item": True}

    except Exception as e:
        logger.warning(f"Error looking up table approvals: {e}")
        for table_name in table_names:
            if table_name not in statuses:
                statuses[table_name] = {"has_release": False, "error": str(e)}


# Module exports
__all__ = [
    'platform_approve',
    'platform_reject',
    'platform_revoke',
    'platform_approvals_list',
    'platform_approval_get',
    'platform_approvals_status'
]
