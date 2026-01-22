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

Created: 17 JAN 2026
"""

import json
import azure.functions as func

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "ApprovalTriggers")


def platform_approve(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to approve a pending dataset.

    POST /api/platform/approve

    Approves a dataset for publication. Updates STAC item with
    app:published=true. For PUBLIC classification, triggers ADF pipeline.

    Request Body:
    {
        "approval_id": "apr-abc123...",  // Required: Approval ID to approve
        "reviewer": "user@example.com",   // Required: Who is approving
        "notes": "Looks good"             // Optional: Review notes
    }

    Alternative - by STAC item:
    {
        "stac_item_id": "my-dataset-v1",  // Find approval by STAC item
        "reviewer": "user@example.com",
        "notes": "Approved via STAC lookup"
    }

    Alternative - by job ID:
    {
        "job_id": "abc123...",            // Find approval by job ID
        "reviewer": "user@example.com"
    }

    Alternative - by Platform request ID (21 JAN 2026):
    {
        "request_id": "a3f2c1b8...",      // Find approval by Platform request ID
        "reviewer": "user@example.com"
    }

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

        # Perform approval
        logger.info(f"Approving {approval_id} by {reviewer}")
        result = approval_service.approve(
            approval_id=approval_id,
            reviewer=reviewer,
            notes=notes
        )

        if result.get('success'):
            approval_data = result.get('approval')
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "approval_id": approval_id,
                    "status": "approved",
                    "action": result.get('action', 'stac_updated'),
                    "adf_run_id": result.get('adf_run_id'),
                    "stac_updated": result.get('stac_updated', False),
                    "classification": approval_data.classification.value if approval_data else None,
                    "message": "Dataset approved successfully"
                }),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )
        else:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": result.get('error'),
                    "error_type": "ApprovalFailed"
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


def platform_revoke(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger to revoke an approved dataset (unapprove).

    POST /api/platform/revoke

    Revokes an approved dataset. This is an audit-logged operation for
    when approved data needs to be unpublished or removed. Updates
    STAC item with revocation properties.

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

        # Perform revocation
        logger.warning(f"AUDIT: Revoking approval {approval_id} by {revoker}. Reason: {reason}")
        result = approval_service.revoke(
            approval_id=approval_id,
            revoker=revoker,
            reason=reason
        )

        if result.get('success'):
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "approval_id": approval_id,
                    "status": "revoked",
                    "stac_updated": result.get('stac_updated', False),
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
        from core.models.promoted import Classification

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
                classification_enum = Classification(classification_filter.lower())
            except ValueError:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Invalid classification: {classification_filter}. Valid values: ouo, public",
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
    'platform_revoke',
    'platform_approvals_list',
    'platform_approval_get',
    'platform_approvals_status'
]
