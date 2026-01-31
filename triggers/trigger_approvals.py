# ============================================================================
# APPROVAL PLATFORM TRIGGERS
# ============================================================================
# STATUS: Trigger - HTTP endpoints for dataset approval workflow
# PURPOSE: Platform API for approving and revoking dataset approvals
# LAST_REVIEWED: 17 JAN 2026
# EXPORTS: platform_approve, platform_revoke, platform_approvals_list
# DEPENDENCIES: services.approval_service
# ============================================================================
"""
Approval Platform Triggers.

HTTP endpoints for the dataset approval workflow:
- POST /api/platform/approve - Approve a pending dataset
- POST /api/platform/revoke - Revoke an approved dataset (unapprove)
- GET /api/platform/approvals - List approvals with filters

These are synchronous operations (no async jobs) since they're simple
state changes to approval records and STAC properties.

V0.8 Entity Architecture (29 JAN 2026):
- Approval now requires clearance_level (ouo or public)
- Updates both DatasetApproval (legacy) and GeospatialAsset (new)
- clearance_level determines access zone (internal vs external)

Created: 17 JAN 2026
Updated: 29 JAN 2026 - V0.8 Entity Architecture
"""

import json
import azure.functions as func

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "ApprovalTriggers")

# V0.8 Entity Architecture imports (29 JAN 2026)
from core.models.asset import ClearanceState


def platform_approve(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to approve a pending dataset.

    POST /api/platform/approve

    Approves a dataset for publication. Updates STAC item with
    app:published=true. For PUBLIC classification, triggers ADF pipeline.

    Request Body:
    {
        "approval_id": "apr-abc123...",    // Required: Approval ID to approve
        "reviewer": "user@example.com",     // Required: Who is approving
        "clearance_level": "ouo",           // Required (V0.8): "ouo" or "public"
        "notes": "Looks good"               // Optional: Review notes
    }

    Alternative - by STAC item:
    {
        "stac_item_id": "my-dataset-v1",   // Find approval by STAC item
        "reviewer": "user@example.com",
        "clearance_level": "ouo",
        "notes": "Approved via STAC lookup"
    }

    Alternative - by job ID:
    {
        "job_id": "abc123...",             // Find approval by job ID
        "reviewer": "user@example.com",
        "clearance_level": "public"        // Will trigger ADF export
    }

    Alternative - by Platform request ID (21 JAN 2026):
    {
        "request_id": "a3f2c1b8...",       // Find approval by Platform request ID
        "reviewer": "user@example.com",
        "clearance_level": "ouo"
    }

    Clearance Levels (V0.8):
    - "ouo": Official Use Only - internal access, no external export
    - "public": Public access - triggers ADF pipeline for external zone export

    Response (success):
    {
        "success": true,
        "approval_id": "apr-abc123...",
        "status": "approved",
        "action": "stac_updated",  // or "adf_triggered" for PUBLIC
        "adf_run_id": "...",       // If PUBLIC classification
        "message": "Dataset approved successfully"
    }

    Response (error):
    {
        "success": false,
        "error": "Cannot approve: status is 'approved', expected 'pending'",
        "error_type": "InvalidStatusTransition"
    }
    """
    logger.info("Platform approve endpoint called")

    try:
        req_body = req.get_json()

        # Extract parameters
        approval_id = req_body.get('approval_id')
        stac_item_id = req_body.get('stac_item_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')  # Platform request ID (21 JAN 2026)
        reviewer = req_body.get('reviewer')
        notes = req_body.get('notes')
        clearance_level_str = req_body.get('clearance_level')  # V0.8: Required (29 JAN 2026)

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

        # V0.8: Validate clearance_level is provided (29 JAN 2026)
        if not clearance_level_str:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "clearance_level is required (V0.8). Must be 'ouo' or 'public'",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Parse clearance level
        try:
            clearance_level = ClearanceState(clearance_level_str.lower())
            if clearance_level == ClearanceState.UNCLEARED:
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

        # Import service lazily to avoid startup issues
        from services.approval_service import ApprovalService
        approval_service = ApprovalService()

        # Resolve approval_id from various inputs
        # Supports: approval_id, stac_item_id, job_id, or request_id (21 JAN 2026)
        if not approval_id:
            if stac_item_id:
                approval = approval_service.get_approval_for_stac_item(stac_item_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for STAC item: {stac_item_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            elif job_id:
                approval = approval_service.get_approval_for_job(job_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for job: {job_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            elif request_id:
                # Resolve request_id → job_id → approval (21 JAN 2026)
                from infrastructure import PlatformRepository
                platform_repo = PlatformRepository()
                platform_request = platform_repo.get_request(request_id)
                if not platform_request:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No platform request found: {request_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
                approval = approval_service.get_approval_for_job(platform_request.job_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for request: {request_id} (job: {platform_request.job_id})",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            else:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": "Must provide approval_id, stac_item_id, job_id, or request_id",
                        "error_type": "ValidationError"
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )

        # Perform approval (legacy DatasetApproval)
        # V0.8 FIX (31 JAN 2026): Pass clearance_level to service (BUG-016)
        logger.info(f"Approving {approval_id} by {reviewer} with clearance={clearance_level.value}")
        result = approval_service.approve(
            approval_id=approval_id,
            reviewer=reviewer,
            notes=notes,
            classification=clearance_level  # V0.8 FIX: Pass clearance level
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

        approval_data = result.get('approval')
        adf_run_id = result.get('adf_run_id')

        # =====================================================================
        # V0.8: Also update GeospatialAsset (29 JAN 2026)
        # V0.8 FIX (31 JAN 2026): Use STAC item ID as fallback lookup (BUG-016)
        # =====================================================================
        asset_updated = False
        asset_id = None
        clearance_warning = None
        try:
            from services.asset_service import AssetService, AssetNotFoundError, AssetStateError
            asset_service = AssetService()

            # Find asset - try multiple lookup methods
            asset = None

            # Method 1: By job_id (from approval record)
            if approval_data and approval_data.job_id:
                asset = asset_service.get_asset_by_job(approval_data.job_id)
                if asset:
                    logger.debug(f"Found asset via job_id lookup: {asset.asset_id[:16]}")

            # Method 2: By STAC item ID (fallback for pre-V0.8 jobs without current_job_id)
            if not asset and approval_data and approval_data.stac_item_id:
                asset = asset_service.get_asset_by_stac_item(approval_data.stac_item_id)
                if asset:
                    logger.debug(f"Found asset via stac_item_id lookup: {asset.asset_id[:16]}")

            if asset:
                try:
                    asset, clearance_warning = asset_service.approve(
                        asset_id=asset.asset_id,
                        reviewer=reviewer,
                        clearance_level=clearance_level,
                        adf_run_id=adf_run_id
                    )
                    asset_updated = True
                    asset_id = asset.asset_id
                    logger.info(f"Updated GeospatialAsset {asset.asset_id[:16]} to clearance={clearance_level.value}")
                    if clearance_warning:
                        logger.warning(f"Clearance change warning: {clearance_warning}")
                except AssetStateError as state_err:
                    # Asset is rejected - log but don't fail
                    logger.warning(f"Asset state error (non-fatal): {state_err}")
            else:
                logger.debug(f"No GeospatialAsset found for approval {approval_id[:16]} (pre-V0.8 data)")
        except Exception as asset_err:
            # Non-fatal: legacy approval succeeded, asset update is optional
            logger.warning(f"Failed to update GeospatialAsset (non-fatal): {asset_err}")

        response_data = {
            "success": True,
            "approval_id": approval_id,
            "status": "approved",
            "action": result.get('action', 'stac_updated'),
            "adf_run_id": adf_run_id,
            "stac_updated": result.get('stac_updated', False),
            "classification": approval_data.classification.value if approval_data else None,
            "clearance_level": clearance_level.value,  # V0.8
            "asset_id": asset_id,  # V0.8
            "asset_updated": asset_updated,  # V0.8
            "message": "Dataset approved successfully"
        }
        # Add warning if clearance was downgraded (e.g., public -> ouo)
        if clearance_warning:
            response_data["warning"] = clearance_warning
            response_data["action_required"] = "manual_external_cleanup"

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
    This is for datasets that fail review (unlike revoke, which is for
    already-approved datasets that need to be unpublished).

    V0.8 Entity Architecture (29 JAN 2026):
    - Updates both DatasetApproval (legacy) and GeospatialAsset (new)
    - Asset moves from pending_review → rejected state

    Request Body:
    {
        "approval_id": "apr-abc123...",       // Required: Approval ID to reject
        "reviewer": "user@example.com",       // Required: Who is rejecting
        "reason": "Data quality issue found"  // Required: Reason for rejection
    }

    Alternative - by STAC item:
    {
        "stac_item_id": "my-dataset-v1",
        "reviewer": "user@example.com",
        "reason": "Missing required metadata"
    }

    Alternative - by job ID:
    {
        "job_id": "abc123...",
        "reviewer": "admin@example.com",
        "reason": "Invalid CRS"
    }

    Alternative - by Platform request ID:
    {
        "request_id": "a3f2c1b8...",
        "reviewer": "admin@example.com",
        "reason": "Failed validation checks"
    }

    Response (success):
    {
        "success": true,
        "approval_id": "apr-abc123...",
        "status": "rejected",
        "asset_id": "...",
        "asset_updated": true,
        "message": "Dataset rejected"
    }

    Response (error):
    {
        "success": false,
        "error": "Cannot reject: status is 'approved', expected 'pending'",
        "error_type": "InvalidStatusTransition"
    }
    """
    logger.info("Platform reject endpoint called")

    try:
        req_body = req.get_json()

        # Extract parameters
        approval_id = req_body.get('approval_id')
        stac_item_id = req_body.get('stac_item_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')
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

        # Import service lazily
        from services.approval_service import ApprovalService
        approval_service = ApprovalService()

        # Resolve approval_id from various inputs
        if not approval_id:
            if stac_item_id:
                approval = approval_service.get_approval_for_stac_item(stac_item_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for STAC item: {stac_item_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            elif job_id:
                approval = approval_service.get_approval_for_job(job_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for job: {job_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            elif request_id:
                from infrastructure import PlatformRepository
                platform_repo = PlatformRepository()
                platform_request = platform_repo.get_request(request_id)
                if not platform_request:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No platform request found: {request_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
                approval = approval_service.get_approval_for_job(platform_request.job_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for request: {request_id} (job: {platform_request.job_id})",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            else:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": "Must provide approval_id, stac_item_id, job_id, or request_id",
                        "error_type": "ValidationError"
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )

        # Perform rejection on legacy DatasetApproval
        logger.info(f"Rejecting {approval_id} by {reviewer}. Reason: {reason}")
        result = approval_service.reject(
            approval_id=approval_id,
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

        approval_data = result.get('approval')

        # =====================================================================
        # V0.8: Also update GeospatialAsset (29 JAN 2026)
        # =====================================================================
        asset_updated = False
        asset_id = None
        try:
            from services.asset_service import AssetService, AssetNotFoundError, AssetStateError
            asset_service = AssetService()

            # Find asset by job_id (from approval record)
            if approval_data and approval_data.job_id:
                asset = asset_service.get_asset_by_job(approval_data.job_id)
                if asset:
                    try:
                        asset = asset_service.reject(
                            asset_id=asset.asset_id,
                            reviewer=reviewer,
                            reason=reason
                        )
                        asset_updated = True
                        asset_id = asset.asset_id
                        logger.info(f"Rejected GeospatialAsset {asset.asset_id[:16]}")
                    except AssetStateError as state_err:
                        logger.warning(f"Asset state mismatch (non-fatal): {state_err}")
                else:
                    logger.debug(f"No GeospatialAsset found for job {approval_data.job_id[:16]} (pre-V0.8 job)")
        except Exception as asset_err:
            logger.warning(f"Failed to update GeospatialAsset (non-fatal): {asset_err}")

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "approval_id": approval_id,
                "status": "rejected",
                "asset_id": asset_id,
                "asset_updated": asset_updated,
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
    when approved data needs to be unpublished or removed. Updates
    STAC item with revocation properties.

    V0.8 Entity Architecture (29 JAN 2026):
    - Also soft-deletes the GeospatialAsset

    IMPORTANT: This is a necessary but undesirable workflow. All revocations
    are logged with full audit trail.

    Request Body:
    {
        "approval_id": "apr-abc123...",       // Required: Approval ID to revoke
        "revoker": "user@example.com",        // Required: Who is revoking
        "reason": "Data quality issue found"  // Required: Reason for revocation
    }

    Alternative - by STAC item:
    {
        "stac_item_id": "my-dataset-v1",
        "revoker": "user@example.com",
        "reason": "Needs to be replaced with updated version"
    }

    Alternative - by job ID:
    {
        "job_id": "abc123...",
        "revoker": "admin@example.com",
        "reason": "Source data was incorrect"
    }

    Alternative - by Platform request ID (21 JAN 2026):
    {
        "request_id": "a3f2c1b8...",
        "revoker": "admin@example.com",
        "reason": "Processing error discovered"
    }

    Response (success):
    {
        "success": true,
        "approval_id": "apr-abc123...",
        "status": "revoked",
        "stac_updated": true,
        "asset_id": "...",
        "asset_deleted": true,
        "warning": "Approved dataset has been revoked - this action is logged for audit",
        "message": "Approval revoked successfully"
    }

    Response (error):
    {
        "success": false,
        "error": "Cannot revoke: status is 'pending', expected 'approved'",
        "error_type": "InvalidStatusTransition"
    }
    """
    logger.info("Platform revoke endpoint called")

    try:
        req_body = req.get_json()

        # Extract parameters
        approval_id = req_body.get('approval_id')
        stac_item_id = req_body.get('stac_item_id')
        job_id = req_body.get('job_id')
        request_id = req_body.get('request_id')  # Platform request ID (21 JAN 2026)
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

        # Import service lazily
        from services.approval_service import ApprovalService
        approval_service = ApprovalService()

        # Resolve approval_id from various inputs
        # Supports: approval_id, stac_item_id, job_id, or request_id (21 JAN 2026)
        if not approval_id:
            if stac_item_id:
                approval = approval_service.get_approval_for_stac_item(stac_item_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for STAC item: {stac_item_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            elif job_id:
                approval = approval_service.get_approval_for_job(job_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for job: {job_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            elif request_id:
                # Resolve request_id → job_id → approval (21 JAN 2026)
                from infrastructure import PlatformRepository
                platform_repo = PlatformRepository()
                platform_request = platform_repo.get_request(request_id)
                if not platform_request:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No platform request found: {request_id}",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
                approval = approval_service.get_approval_for_job(platform_request.job_id)
                if approval:
                    approval_id = approval.approval_id
                else:
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"No approval found for request: {request_id} (job: {platform_request.job_id})",
                            "error_type": "NotFound"
                        }),
                        status_code=404,
                        headers={"Content-Type": "application/json"}
                    )
            else:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": "Must provide approval_id, stac_item_id, job_id, or request_id",
                        "error_type": "ValidationError"
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )

        # Perform revocation on legacy DatasetApproval
        logger.warning(f"AUDIT: Revoking approval {approval_id} by {revoker}. Reason: {reason}")
        result = approval_service.revoke(
            approval_id=approval_id,
            revoker=revoker,
            reason=reason
        )

        if result.get('success'):
            approval_data = result.get('approval')

            # =====================================================================
            # V0.8: Also soft-delete GeospatialAsset (29 JAN 2026)
            # =====================================================================
            asset_deleted = False
            asset_id = None
            try:
                from services.asset_service import AssetService, AssetNotFoundError
                asset_service = AssetService()

                # Find asset by job_id (from approval record)
                if approval_data and approval_data.job_id:
                    asset = asset_service.get_asset_by_job(approval_data.job_id)
                    if asset:
                        asset_service.soft_delete(
                            asset_id=asset.asset_id,
                            deleted_by=revoker
                        )
                        asset_deleted = True
                        asset_id = asset.asset_id
                        logger.info(f"Soft-deleted GeospatialAsset {asset.asset_id[:16]} on revocation")
                    else:
                        logger.debug(f"No GeospatialAsset found for job (pre-V0.8 job)")
            except Exception as asset_err:
                logger.warning(f"Failed to soft-delete GeospatialAsset (non-fatal): {asset_err}")

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "approval_id": approval_id,
                    "status": "revoked",
                    "stac_updated": result.get('stac_updated', False),
                    "asset_id": asset_id,
                    "asset_deleted": asset_deleted,
                    "warning": result.get('warning'),
                    "message": "Approval revoked successfully"
                }),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )
        else:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": result.get('error'),
                    "error_type": "RevocationFailed"
                }),
                status_code=400,
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
    HTTP trigger to list approvals with filters.

    GET /api/platform/approvals

    Query Parameters:
        status: Filter by status (pending, approved, rejected, revoked)
        classification: Filter by classification (ouo, public)
        limit: Max results (default 100)
        offset: Pagination offset (default 0)

    Response:
    {
        "success": true,
        "approvals": [...],
        "count": 25,
        "limit": 100,
        "offset": 0,
        "status_counts": {
            "pending": 5,
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
        classification_filter = req.params.get('classification')
        limit = int(req.params.get('limit', 100))
        offset = int(req.params.get('offset', 0))

        # Import service lazily
        from services.approval_service import ApprovalService
        from core.models.approval import ApprovalStatus
        from core.models.stac import AccessLevel

        approval_service = ApprovalService()

        # Parse filters
        status_enum = None
        if status_filter:
            try:
                status_enum = ApprovalStatus(status_filter.lower())
            except ValueError:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Invalid status: {status_filter}. Valid values: pending, approved, rejected, revoked",
                        "error_type": "ValidationError"
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )

        classification_enum = None
        if classification_filter:
            try:
                # NOTE: RESTRICTED is defined but NOT YET SUPPORTED
                classification_enum = AccessLevel(classification_filter.lower())
            except ValueError:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Invalid classification: {classification_filter}. Valid values: ouo, public (restricted not yet supported)",
                        "error_type": "ValidationError"
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )

        # Fetch approvals
        approvals = approval_service.list_approvals(
            status=status_enum,
            classification=classification_enum,
            limit=limit,
            offset=offset
        )

        # Get status counts
        status_counts = approval_service.get_status_counts()

        # Convert to JSON-serializable format
        approvals_data = []
        for approval in approvals:
            approval_dict = approval.model_dump(mode='json')
            # Ensure enum values are strings
            approval_dict['status'] = approval.status.value if hasattr(approval.status, 'value') else str(approval.status)
            approval_dict['classification'] = approval.classification.value if hasattr(approval.classification, 'value') else str(approval.classification)
            approvals_data.append(approval_dict)

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "approvals": approvals_data,
                "count": len(approvals_data),
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
    HTTP trigger to get a single approval by ID.

    GET /api/platform/approvals/{approval_id}

    Response:
    {
        "success": true,
        "approval": {...}
    }
    """
    logger.info("Platform approval get endpoint called")

    try:
        # Get approval_id from route
        approval_id = req.route_params.get('approval_id')

        if not approval_id:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "approval_id is required",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Import service lazily
        from services.approval_service import ApprovalService
        approval_service = ApprovalService()

        approval = approval_service.get_approval(approval_id)

        if not approval:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Approval not found: {approval_id}",
                    "error_type": "NotFound"
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        # Convert to JSON-serializable format
        approval_dict = approval.model_dump(mode='json')
        approval_dict['status'] = approval.status.value if hasattr(approval.status, 'value') else str(approval.status)
        approval_dict['classification'] = approval.classification.value if hasattr(approval.classification, 'value') else str(approval.classification)

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "approval": approval_dict
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

    Response:
    {
        "success": true,
        "statuses": {
            "item1": {
                "has_approval": true,
                "approval_id": "apr-abc123",
                "status": "approved",
                "is_approved": true,
                "reviewer": "user@example.com",
                "reviewed_at": "2026-01-17T..."
            },
            "item2": {
                "has_approval": false
            }
        }
    }
    """
    logger.info("Platform approvals status endpoint called")

    try:
        # Get query parameters
        stac_item_ids_param = req.params.get('stac_item_ids', '')
        stac_collection_ids_param = req.params.get('stac_collection_ids', '')
        table_names_param = req.params.get('table_names', '')  # For OGC Features (vector tables)

        # Parse comma-separated IDs
        stac_item_ids = [id.strip() for id in stac_item_ids_param.split(',') if id.strip()]
        stac_collection_ids = [id.strip() for id in stac_collection_ids_param.split(',') if id.strip()]
        table_names = [name.strip() for name in table_names_param.split(',') if name.strip()]

        if not stac_item_ids and not stac_collection_ids and not table_names:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Must provide stac_item_ids or stac_collection_ids query parameter",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Import service lazily
        from services.approval_service import ApprovalService
        from core.models.approval import ApprovalStatus

        approval_service = ApprovalService()
        statuses = {}

        # Look up by STAC item IDs
        for item_id in stac_item_ids:
            approval = approval_service.get_approval_for_stac_item(item_id)
            if approval:
                is_approved = approval.status == ApprovalStatus.APPROVED
                statuses[item_id] = {
                    "has_approval": True,
                    "approval_id": approval.approval_id,
                    "status": approval.status.value,
                    "is_approved": is_approved,
                    "reviewer": approval.reviewer,
                    "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None
                }
            else:
                statuses[item_id] = {"has_approval": False}

        # Look up by STAC collection IDs
        # For collections, we check if ANY item in that collection has an approval
        # This is a simplified approach - could be enhanced to check all items
        for collection_id in stac_collection_ids:
            # Query approvals by collection_id
            approvals = approval_service.repo.list_by_collection(collection_id)
            if approvals:
                # Check if any are approved
                approved_count = sum(1 for a in approvals if a.status == ApprovalStatus.APPROVED)
                any_approved = approved_count > 0
                statuses[collection_id] = {
                    "has_approval": True,
                    "approval_count": len(approvals),
                    "approved_count": approved_count,
                    "is_approved": any_approved,
                    "status": "approved" if any_approved else approvals[0].status.value
                }
            else:
                statuses[collection_id] = {"has_approval": False}

        # Look up by table names (for OGC Features / vector tables)
        # This looks up the stac_item_id from geo.table_catalog (21 JAN 2026)
        if table_names:
            try:
                from infrastructure.postgresql import PostgreSQLRepository
                repo = PostgreSQLRepository()

                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        for table_name in table_names:
                            # Look up stac_item_id from table_catalog (21 JAN 2026)
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
                                # Found STAC item - check approval
                                stac_item_id = row['stac_item_id']
                                approval = approval_service.get_approval_for_stac_item(stac_item_id)

                                if approval:
                                    is_approved = approval.status == ApprovalStatus.APPROVED
                                    statuses[table_name] = {
                                        "has_approval": True,
                                        "approval_id": approval.approval_id,
                                        "status": approval.status.value,
                                        "is_approved": is_approved,
                                        "stac_item_id": stac_item_id,
                                        "reviewer": approval.reviewer,
                                        "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None
                                    }
                                else:
                                    statuses[table_name] = {
                                        "has_approval": False,
                                        "stac_item_id": stac_item_id
                                    }
                            else:
                                # No STAC item linked to this table
                                statuses[table_name] = {"has_approval": False, "no_stac_item": True}
            except Exception as e:
                logger.warning(f"Error looking up table approvals: {e}")
                # Don't fail the whole request - just mark these as unknown
                for table_name in table_names:
                    if table_name not in statuses:
                        statuses[table_name] = {"has_approval": False, "error": str(e)}

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
