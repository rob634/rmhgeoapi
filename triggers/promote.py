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
        "stac_collection_id": "fathom-pluvial",    // Required if not ogc_features_collection_id or stac_item_id
        "ogc_features_collection_id": "roads",     // Required if not stac_collection_id or stac_item_id (26 DEC 2025)
        "stac_item_id": "item-123",                // Required if not stac/ogc collection
        "title": "Custom Title",                   // Optional - override source title
        "description": "Custom description",       // Optional - override source description
        "tags": ["flood", "hazard"],               // Optional - categorization tags
        "gallery": true,                           // Optional - add to gallery
        "gallery_order": 1,                        // Optional - gallery display order
        "viewer_config": {...},                    // Optional - viewer settings
        "style_id": "flood-style",                 // Optional - OGC Style ID
        "style": {"title": "...", "spec": {...}},  // Optional - inline style creation (26 DEC 2025)
        "is_system_reserved": true,                // Optional - mark as system-critical (23 DEC 2025)
        "system_role": "admin0_boundaries"         // Optional - system role for discovery
    }

    Query Parameters:
        gallery=true: Also add to gallery when promoting

    System Roles (23 DEC 2025):
        admin0_boundaries: Country boundaries for ISO3 attribution
        h3_land_grid: H3 land-only grid cells for spatial operations
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

            # Collection reference (one required)
            # Accept either stac_collection_id or ogc_features_collection_id
            stac_collection_id = body.get('stac_collection_id') or body.get('ogc_features_collection_id')
            stac_item_id = body.get('stac_item_id')

            if not stac_collection_id and not stac_item_id:
                return func.HttpResponse(
                    json.dumps({
                        'success': False,
                        'error': 'Must specify either stac_collection_id, ogc_features_collection_id, or stac_item_id'
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

            # NEW (26 DEC 2025): Inline style creation
            # If 'style' object provided, create OGC style and use its ID
            style_spec = body.get('style')
            created_style_id = None
            if style_spec and isinstance(style_spec, dict):
                try:
                    from ogc_styles.repository import OGCStylesRepository
                    styles_repo = OGCStylesRepository()

                    # Determine collection_id for style association
                    collection_id = stac_collection_id or stac_item_id

                    # Generate style_id if not provided
                    inline_style_id = style_spec.get('id') or f"{promoted_id}-default"
                    inline_title = style_spec.get('title') or f"{promoted_id} Style"
                    inline_spec = style_spec.get('spec', style_spec)

                    # Create style in database
                    styles_repo.create_style(
                        collection_id=collection_id,
                        style_id=inline_style_id,
                        title=inline_title,
                        description=style_spec.get('description'),
                        style_spec=inline_spec,
                        is_default=True
                    )

                    # Use this style for promotion
                    style_id = inline_style_id
                    created_style_id = inline_style_id
                    logger.info(f"Created style '{style_id}' for collection '{collection_id}'")

                except Exception as style_err:
                    logger.warning(f"Failed to create inline style: {style_err}")
                    # Continue without style - don't fail the promotion

            # Gallery flag (from body or query param)
            gallery = body.get('gallery', False)
            if req.params.get('gallery', '').lower() == 'true':
                gallery = True
            gallery_order = body.get('gallery_order')

            # System reserved flags (23 DEC 2025)
            is_system_reserved = body.get('is_system_reserved', False)
            system_role = body.get('system_role')

            # Classification (24 DEC 2025)
            classification = body.get('classification')

            # Promote
            service = PromoteService()
            result = service.promote(
                promoted_id=promoted_id,
                stac_collection_id=stac_collection_id,
                stac_item_id=stac_item_id,
                title=title,
                description=description,
                tags=tags,
                classification=classification,
                gallery=gallery,
                gallery_order=gallery_order,
                viewer_config=viewer_config,
                style_id=style_id,
                is_system_reserved=is_system_reserved,
                system_role=system_role
            )

            status_code = 201 if result.get('action') == 'created' else 200
            if not result.get('success'):
                status_code = 400

            # Add style_id to response if style was created (26 DEC 2025)
            if created_style_id:
                result['style_id'] = created_style_id
                collection_id = stac_collection_id or stac_item_id
                result['style_url'] = f"/api/features/collections/{collection_id}/styles/{created_style_id}"

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
        "style_id": "new-style",
        "is_system_reserved": true,            // Optional - mark as system-critical (23 DEC 2025)
        "system_role": "admin0_boundaries"     // Optional - system role for discovery
    }

    DELETE Query Parameters (23 DEC 2025):
        confirm_system=true: Required to delete system-reserved datasets
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

            # Support updating system reserved flags (23 DEC 2025)
            # If not provided, keep existing values
            is_system_reserved = body.get('is_system_reserved', existing.get('is_system_reserved', False))
            system_role = body.get('system_role', existing.get('system_role'))

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
                style_id=body.get('style_id'),
                is_system_reserved=is_system_reserved,
                system_role=system_role
            )

            status_code = 200 if result.get('success') else 400
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                mimetype="application/json",
                status_code=status_code
            )

        elif method == "DELETE":
            # Demote - require confirmation for system-reserved datasets (23 DEC 2025)
            confirm_system = req.params.get('confirm_system', '').lower() == 'true'

            result = service.demote(promoted_id, confirm_system=confirm_system)

            # Determine status code based on result
            if result.get('success'):
                status_code = 200
            elif 'system-reserved' in result.get('error', '').lower():
                status_code = 403  # Forbidden - need confirmation
            else:
                status_code = 404  # Not found

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
            except (ValueError, TypeError) as e:
                # No body or invalid JSON is fine for this endpoint
                logger.debug(f"No JSON body for gallery add (ok): {e}")

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


def handle_system_reserved(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle GET /api/promote/system.

    Returns all system-reserved datasets (23 DEC 2025).

    Query Parameters:
        role: Filter by system_role (e.g., 'admin0_boundaries')

    Response:
    {
        "success": true,
        "count": 2,
        "data": [
            {
                "promoted_id": "curated-admin0",
                "system_role": "admin0_boundaries",
                "is_system_reserved": true,
                ...
            }
        ]
    }
    """
    try:
        service = PromoteService()

        # Check for role filter
        role = req.params.get('role')

        if role:
            # Get specific system role
            dataset = service.get_by_system_role(role)
            if dataset:
                return func.HttpResponse(
                    json.dumps({
                        'success': True,
                        'count': 1,
                        'data': [dataset]
                    }, indent=2, default=str),
                    mimetype="application/json",
                    status_code=200
                )
            else:
                return func.HttpResponse(
                    json.dumps({
                        'success': False,
                        'error': f"No system-reserved dataset with role '{role}' found",
                        'available_roles': ['admin0_boundaries', 'h3_land_grid']
                    }, indent=2),
                    mimetype="application/json",
                    status_code=404
                )
        else:
            # List all system-reserved datasets
            datasets = service.list_system_reserved()
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
        logger.exception(f"Error in handle_system_reserved: {e}")
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
    'handle_gallery_list',
    'handle_system_reserved'
]
