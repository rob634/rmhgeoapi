# ============================================================================
# CLAUDE CONTEXT - PROMOTE API TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: HTTP triggers for dataset promotion system
# PURPOSE: CRUD + gallery operations for promoted datasets
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: handle_promote, handle_promote_item, handle_gallery, handle_gallery_list
# DEPENDENCIES: services.promote_service
# ============================================================================
"""
Promote API Triggers.

HTTP endpoints for the dataset promotion system:
- POST /api/promote - Promote a STAC collection/item
- GET /api/promote - List all promoted datasets
- GET /api/promote/{promoted_id} - Get promoted dataset details
- PUT /api/promote/{promoted_id} - Update promoted dataset
- DELETE /api/promote/{promoted_id} - Demote (remove entirely)
- POST /api/promote/{promoted_id}/gallery - Add to gallery
- DELETE /api/promote/{promoted_id}/gallery - Remove from gallery
- GET /api/promote/gallery - List gallery items

Exports:
    handle_promote: POST/GET for /api/promote
    handle_promote_item: GET/PUT/DELETE for /api/promote/{promoted_id}
    handle_gallery: POST/DELETE for /api/promote/{promoted_id}/gallery
    handle_gallery_list: GET for /api/promote/gallery

Created: 22 DEC 2025
"""

import azure.functions as func
import json
import logging

from services.promote_service import PromoteService

logger = logging.getLogger(__name__)


def handle_promote(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle POST/GET /api/promote.

    POST: Promote a STAC collection/item
    GET: List all promoted datasets

    POST Body:
    {
        "promoted_id": "fathom-flood-100yr",       // Required - unique identifier
        "stac_collection_id": "fathom-pluvial",    // Required if not stac_item_id
        "stac_item_id": "item-123",                // Required if not stac_collection_id
        "title": "Custom Title",                   // Optional - override STAC title
        "description": "Custom description",       // Optional - override STAC description
        "tags": ["flood", "hazard"],               // Optional - categorization tags
        "gallery": true,                           // Optional - add to gallery
        "gallery_order": 1,                        // Optional - gallery display order
        "viewer_config": {...},                    // Optional - viewer settings
        "style_id": "flood-style"                  // Optional - OGC Style ID
    }

    Query Parameters:
        gallery=true: Also add to gallery when promoting
    """
    try:
        method = req.method.upper()

        if method == "GET":
            # List all promoted datasets
            service = PromoteService()
            datasets = service.list_all()
            return func.HttpResponse(
                json.dumps({
                    'success': True,
                    'count': len(datasets),
                    'data': datasets
                }, indent=2, default=str),
                mimetype="application/json",
                status_code=200
            )

        elif method == "POST":
            # Promote a dataset
            body = req.get_json()

            # Required field
            promoted_id = body.get('promoted_id')
            if not promoted_id:
                return func.HttpResponse(
                    json.dumps({
                        'success': False,
                        'error': 'Missing required parameter: promoted_id'
                    }, indent=2),
                    mimetype="application/json",
                    status_code=400
                )

            # STAC reference (one required)
            stac_collection_id = body.get('stac_collection_id')
            stac_item_id = body.get('stac_item_id')

            if not stac_collection_id and not stac_item_id:
                return func.HttpResponse(
                    json.dumps({
                        'success': False,
                        'error': 'Must specify either stac_collection_id or stac_item_id'
                    }, indent=2),
                    mimetype="application/json",
                    status_code=400
                )

            # Optional fields
            title = body.get('title')
            description = body.get('description')
            tags = body.get('tags')
            viewer_config = body.get('viewer_config')
            style_id = body.get('style_id')

            # Gallery flag (from body or query param)
            gallery = body.get('gallery', False)
            if req.params.get('gallery', '').lower() == 'true':
                gallery = True
            gallery_order = body.get('gallery_order')

            # Promote
            service = PromoteService()
            result = service.promote(
                promoted_id=promoted_id,
                stac_collection_id=stac_collection_id,
                stac_item_id=stac_item_id,
                title=title,
                description=description,
                tags=tags,
                gallery=gallery,
                gallery_order=gallery_order,
                viewer_config=viewer_config,
                style_id=style_id
            )

            status_code = 201 if result.get('action') == 'created' else 200
            if not result.get('success'):
                status_code = 400

            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                mimetype="application/json",
                status_code=status_code
            )

        else:
            return func.HttpResponse(
                json.dumps({
                    'success': False,
                    'error': f'Method {method} not allowed'
                }, indent=2),
                mimetype="application/json",
                status_code=405
            )

    except json.JSONDecodeError as e:
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': f'Invalid JSON: {str(e)}'
            }, indent=2),
            mimetype="application/json",
            status_code=400
        )
    except Exception as e:
        logger.exception(f"Error in handle_promote: {e}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e)
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )


def handle_promote_item(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle GET/PUT/DELETE /api/promote/{promoted_id}.

    GET: Get promoted dataset details
    PUT: Update promoted dataset
    DELETE: Demote (remove from promoted entirely)

    PUT Body (all fields optional):
    {
        "title": "New Title",
        "description": "New description",
        "tags": ["new", "tags"],
        "viewer_config": {...},
        "style_id": "new-style"
    }
    """
    try:
        promoted_id = req.route_params.get('promoted_id')
        if not promoted_id:
            return func.HttpResponse(
                json.dumps({
                    'success': False,
                    'error': 'Missing promoted_id in path'
                }, indent=2),
                mimetype="application/json",
                status_code=400
            )

        method = req.method.upper()
        service = PromoteService()

        if method == "GET":
            # Get details
            dataset = service.get(promoted_id)
            if dataset:
                return func.HttpResponse(
                    json.dumps({
                        'success': True,
                        'data': dataset
                    }, indent=2, default=str),
                    mimetype="application/json",
                    status_code=200
                )
            else:
                return func.HttpResponse(
                    json.dumps({
                        'success': False,
                        'error': f"Promoted dataset '{promoted_id}' not found"
                    }, indent=2),
                    mimetype="application/json",
                    status_code=404
                )

        elif method == "PUT":
            # Update
            body = req.get_json()

            # Re-promote with updates (uses same promote logic)
            existing = service.get(promoted_id)
            if not existing:
                return func.HttpResponse(
                    json.dumps({
                        'success': False,
                        'error': f"Promoted dataset '{promoted_id}' not found"
                    }, indent=2),
                    mimetype="application/json",
                    status_code=404
                )

            result = service.promote(
                promoted_id=promoted_id,
                stac_collection_id=existing.get('stac_collection_id'),
                stac_item_id=existing.get('stac_item_id'),
                title=body.get('title'),
                description=body.get('description'),
                tags=body.get('tags'),
                gallery=existing.get('in_gallery', False),
                gallery_order=body.get('gallery_order'),
                viewer_config=body.get('viewer_config'),
                style_id=body.get('style_id')
            )

            status_code = 200 if result.get('success') else 400
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                mimetype="application/json",
                status_code=status_code
            )

        elif method == "DELETE":
            # Demote
            result = service.demote(promoted_id)
            status_code = 200 if result.get('success') else 404
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                mimetype="application/json",
                status_code=status_code
            )

        else:
            return func.HttpResponse(
                json.dumps({
                    'success': False,
                    'error': f'Method {method} not allowed'
                }, indent=2),
                mimetype="application/json",
                status_code=405
            )

    except json.JSONDecodeError as e:
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': f'Invalid JSON: {str(e)}'
            }, indent=2),
            mimetype="application/json",
            status_code=400
        )
    except Exception as e:
        logger.exception(f"Error in handle_promote_item: {e}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e)
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )


def handle_gallery(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle POST/DELETE /api/promote/{promoted_id}/gallery.

    POST: Add to gallery
    DELETE: Remove from gallery (keep promoted)

    POST Body (optional):
    {
        "order": 1  // Optional - gallery display order
    }
    """
    try:
        promoted_id = req.route_params.get('promoted_id')
        if not promoted_id:
            return func.HttpResponse(
                json.dumps({
                    'success': False,
                    'error': 'Missing promoted_id in path'
                }, indent=2),
                mimetype="application/json",
                status_code=400
            )

        method = req.method.upper()
        service = PromoteService()

        if method == "POST":
            # Add to gallery
            order = None
            try:
                body = req.get_json()
                order = body.get('order')
            except:
                pass  # No body is fine

            result = service.add_to_gallery(promoted_id, order)
            status_code = 200 if result.get('success') else 404
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                mimetype="application/json",
                status_code=status_code
            )

        elif method == "DELETE":
            # Remove from gallery
            result = service.remove_from_gallery(promoted_id)
            status_code = 200 if result.get('success') else 404
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                mimetype="application/json",
                status_code=status_code
            )

        else:
            return func.HttpResponse(
                json.dumps({
                    'success': False,
                    'error': f'Method {method} not allowed'
                }, indent=2),
                mimetype="application/json",
                status_code=405
            )

    except Exception as e:
        logger.exception(f"Error in handle_gallery: {e}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e)
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )


def handle_gallery_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle GET /api/promote/gallery.

    Returns gallery items in display order.
    """
    try:
        service = PromoteService()
        datasets = service.list_gallery()

        return func.HttpResponse(
            json.dumps({
                'success': True,
                'count': len(datasets),
                'data': datasets
            }, indent=2, default=str),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logger.exception(f"Error in handle_gallery_list: {e}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e)
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )


# Module exports
__all__ = [
    'handle_promote',
    'handle_promote_item',
    'handle_gallery',
    'handle_gallery_list'
]
