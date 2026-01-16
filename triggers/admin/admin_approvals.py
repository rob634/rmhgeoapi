# ============================================================================
# DATASET APPROVALS ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for dataset approval routes
# PURPOSE: QA workflow endpoints for reviewing and approving datasets
# CREATED: 16 JAN 2026
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
Dataset Approvals Admin Blueprint - QA workflow routes.

Routes (6 total):
    List & Get (2):
        GET  /api/approvals           - List approvals with filters
        GET  /api/approvals/{id}      - Get specific approval

    Actions (3):
        POST /api/approvals/{id}/approve   - Approve dataset
        POST /api/approvals/{id}/reject    - Reject dataset
        POST /api/approvals/{id}/resubmit  - Resubmit rejected dataset

    Test (1):
        POST /api/approvals/test      - Create test approval (dev only)

Classification determines post-approval action:
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
    List dataset approvals with optional filters.

    GET /api/approvals?status=pending&limit=50&offset=0

    Query Parameters:
        status: Filter by status (pending, approved, rejected)
        classification: Filter by classification (ouo, public)
        limit: Maximum results (default: 50, max: 200)
        offset: Pagination offset (default: 0)

    Returns:
        JSON array of approval records
    """
    try:
        from services.approval_service import ApprovalService
        from core.models import ApprovalStatus
        from core.models.promoted import Classification

        service = ApprovalService()

        # Parse query parameters
        status_str = req.params.get('status')
        classification_str = req.params.get('classification')
        limit = min(int(req.params.get('limit', 50)), 200)
        offset = int(req.params.get('offset', 0))

        # Convert string to enums
        status = None
        if status_str:
            try:
                status = ApprovalStatus(status_str.lower())
            except ValueError:
                return func.HttpResponse(
                    json.dumps({
                        'error': f"Invalid status '{status_str}'. Must be: pending, approved, rejected"
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

        classification = None
        if classification_str:
            try:
                classification = Classification(classification_str.lower())
            except ValueError:
                return func.HttpResponse(
                    json.dumps({
                        'error': f"Invalid classification '{classification_str}'. Must be: ouo, public"
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

        # Get approvals
        approvals = service.list_approvals(
            status=status,
            classification=classification,
            limit=limit,
            offset=offset
        )

        # Get status counts for summary
        counts = service.get_status_counts()

        result = {
            'approvals': [a.model_dump(mode='json') for a in approvals],
            'count': len(approvals),
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
    Get a specific approval by ID.

    GET /api/approvals/{approval_id}

    Returns:
        Approval record with full details
    """
    try:
        from services.approval_service import ApprovalService

        approval_id = req.route_params.get('approval_id')
        if not approval_id:
            return func.HttpResponse(
                json.dumps({'error': 'approval_id is required'}),
                status_code=400,
                mimetype='application/json'
            )

        service = ApprovalService()
        approval = service.get_approval(approval_id)

        if not approval:
            return func.HttpResponse(
                json.dumps({'error': f"Approval not found: {approval_id}"}),
                status_code=404,
                mimetype='application/json'
            )

        return func.HttpResponse(
            json.dumps(approval.model_dump(mode='json'), indent=2, default=str),
            status_code=200,
            mimetype='application/json'
        )

    except Exception as e:
        logger.error(f"Error getting approval: {e}", exc_info=True)
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
    Approve a dataset for publication.

    POST /api/approvals/{approval_id}/approve

    Body:
        {
            "reviewer": "analyst@example.com",  // Required
            "notes": "Looks good"               // Optional
        }

    Returns:
        {
            "success": true,
            "approval": {...},
            "action": "stac_updated" | "adf_triggered",
            "adf_run_id": "..." (if PUBLIC)
        }

    Actions:
        - Updates STAC item with app:published=true
        - If PUBLIC classification, triggers ADF pipeline
    """
    try:
        from services.approval_service import ApprovalService

        approval_id = req.route_params.get('approval_id')
        if not approval_id:
            return func.HttpResponse(
                json.dumps({'error': 'approval_id is required'}),
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

        notes = body.get('notes')

        logger.info(f"Approve request: {approval_id} by {reviewer}")

        service = ApprovalService()
        result = service.approve(
            approval_id=approval_id,
            reviewer=reviewer,
            notes=notes
        )

        if result['success']:
            # Serialize approval if present
            if 'approval' in result and result['approval']:
                result['approval'] = result['approval'].model_dump(mode='json')

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
        logger.error(f"Error approving dataset: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


@bp.route(route="approvals/{approval_id}/reject", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def reject_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """
    Reject a dataset.

    POST /api/approvals/{approval_id}/reject

    Body:
        {
            "reviewer": "analyst@example.com",  // Required
            "reason": "Data quality issue"      // Required
        }

    Returns:
        {
            "success": true,
            "approval": {...}
        }
    """
    try:
        from services.approval_service import ApprovalService

        approval_id = req.route_params.get('approval_id')
        if not approval_id:
            return func.HttpResponse(
                json.dumps({'error': 'approval_id is required'}),
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

        logger.info(f"Reject request: {approval_id} by {reviewer}")

        service = ApprovalService()
        result = service.reject(
            approval_id=approval_id,
            reviewer=reviewer,
            reason=reason
        )

        if result['success']:
            if 'approval' in result and result['approval']:
                result['approval'] = result['approval'].model_dump(mode='json')

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
        logger.error(f"Error rejecting dataset: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


@bp.route(route="approvals/{approval_id}/resubmit", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def resubmit_approval(req: func.HttpRequest) -> func.HttpResponse:
    """
    Resubmit a rejected approval back to pending status.

    POST /api/approvals/{approval_id}/resubmit

    Returns:
        {
            "success": true,
            "approval": {...}
        }
    """
    try:
        from services.approval_service import ApprovalService

        approval_id = req.route_params.get('approval_id')
        if not approval_id:
            return func.HttpResponse(
                json.dumps({'error': 'approval_id is required'}),
                status_code=400,
                mimetype='application/json'
            )

        logger.info(f"Resubmit request: {approval_id}")

        service = ApprovalService()
        result = service.resubmit(approval_id)

        if result['success']:
            if 'approval' in result and result['approval']:
                result['approval'] = result['approval'].model_dump(mode='json')

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
        logger.error(f"Error resubmitting approval: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


# ============================================================================
# TEST (1 route)
# ============================================================================

@bp.route(route="approvals/test", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def create_test_approval(req: func.HttpRequest) -> func.HttpResponse:
    """
    Create a test approval for development/testing.

    POST /api/approvals/test

    Body (optional):
        {
            "job_id": "test-job-123",      // Default: test-job-{timestamp}
            "classification": "ouo"        // Default: ouo
        }

    Returns:
        Created test approval
    """
    try:
        from services.approval_service import ApprovalService
        from datetime import datetime

        # Parse body
        try:
            body = req.get_json()
        except ValueError:
            body = {}

        job_id = body.get('job_id', f"test-job-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        classification = body.get('classification', 'ouo')

        logger.info(f"Creating test approval: job_id={job_id}, classification={classification}")

        service = ApprovalService()
        approval = service.create_test_approval(
            job_id=job_id,
            job_type='test_job',
            classification=classification
        )

        return func.HttpResponse(
            json.dumps({
                'success': True,
                'message': 'Test approval created',
                'approval': approval.model_dump(mode='json')
            }, indent=2, default=str),
            status_code=201,
            mimetype='application/json'
        )

    except Exception as e:
        logger.error(f"Error creating test approval: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            status_code=500,
            mimetype='application/json'
        )


# Module exports
__all__ = ['bp']
