# ============================================================================
# PLATFORM BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Platform anti-corruption layer
# PURPOSE: Azure Functions Blueprint with all platform endpoints
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 5 Platform Blueprint
# ============================================================================
"""
Platform Blueprint.

Contains all platform endpoints for external application integration (DDH).
This is the anti-corruption layer between external apps and CoreMachine.

Register this blueprint in function_app.py conditionally based on APP_MODE:
    if _app_mode.has_platform_endpoints:
        from triggers.platform import platform_bp
        app.register_functions(platform_bp)

Endpoint Groups:
    1. Submit/Status - Request submission and monitoring
    2. Diagnostics - Health, failures, lineage, validation
    3. Unpublish - Consolidated data removal
    4. Approvals - Dataset approval workflow
    5. Catalog - B2B STAC access for DDH
"""

import azure.functions as func

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "PlatformBlueprint")

# Create Blueprint
bp = func.Blueprint()


# ============================================================================
# SUBMIT/STATUS ENDPOINTS
# ============================================================================

@bp.route(route="platform/submit", methods=["POST"])
def platform_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a platform request from external application (DDH).

    POST /api/platform/submit

    Body:
        {
            "dataset_id": "landsat-8",
            "resource_id": "LC08_L1TP_044034_20210622",
            "version_id": "v1.0",
            "container_name": "bronze-rasters",
            "file_name": "example.tif",
            "service_name": "Landsat 8 Scene",
            "client_id": "ddh"
        }

    Returns:
        {
            "success": true,
            "request_id": "abc123...",
            "status": "processing",
            "jobs_created": ["job1", "job2", "job3"],
            "monitor_url": "/api/platform/status/abc123"
        }
    """
    from triggers.trigger_platform import platform_request_submit
    return platform_request_submit(req)


@bp.route(route="platform/status/{request_id}", methods=["GET"])
async def platform_status_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get status of a platform request or job (consolidated endpoint).

    GET /api/platform/status/{id}

    The {id} parameter can be EITHER:
    - A request_id (Platform request identifier)
    - A job_id (CoreMachine job identifier)

    The endpoint auto-detects which type of ID was provided.
    Returns detailed status including DDH identifiers and CoreMachine job status.
    """
    from triggers.trigger_platform_status import platform_request_status
    return await platform_request_status(req)


@bp.route(route="platform/status", methods=["GET"])
async def platform_status_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all platform requests.

    GET /api/platform/status?limit=100&status=pending

    Returns list of all platform requests with optional filtering.
    """
    from triggers.trigger_platform_status import platform_request_status
    return await platform_request_status(req)


# ============================================================================
# DIAGNOSTICS ENDPOINTS (F7.12 - 15 JAN 2026)
# ============================================================================

@bp.route(route="platform/health", methods=["GET"])
async def platform_health_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Simplified system readiness check for external apps.

    GET /api/platform/health

    Returns simplified health status (ready_for_jobs, queue backlog, etc.)
    without exposing internal details like enum errors or storage accounts.
    """
    from triggers.trigger_platform_status import platform_health
    return await platform_health(req)


@bp.route(route="platform/failures", methods=["GET"])
async def platform_failures_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Recent failures with sanitized error summaries.

    GET /api/platform/failures?hours=24&limit=20

    Returns failure patterns and recent failures with sanitized messages
    (no internal paths, secrets, or stack traces).
    """
    from triggers.trigger_platform_status import platform_failures
    return await platform_failures(req)


@bp.route(route="platform/lineage/{request_id}", methods=["GET"])
async def platform_lineage_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Data lineage trace by Platform request ID.

    GET /api/platform/lineage/{request_id}

    Returns source -> processing -> output lineage for a Platform request.
    """
    from triggers.trigger_platform_status import platform_lineage
    return await platform_lineage(req)


@bp.route(route="platform/validate", methods=["POST"])
async def platform_validate_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Pre-flight validation before job submission.

    POST /api/platform/validate

    Validates a file exists, returns size, recommended job type, and
    estimated processing time before actually submitting a job.

    Body: {"data_type": "raster", "container_name": "...", "blob_name": "..."}
    """
    from triggers.trigger_platform_status import platform_validate
    return await platform_validate(req)


# ============================================================================
# UNPUBLISH ENDPOINT (Consolidated 21 JAN 2026)
# ============================================================================

@bp.route(route="platform/unpublish", methods=["POST"])
def platform_unpublish_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Consolidated unpublish endpoint - auto-detects data type.

    POST /api/platform/unpublish

    Automatically detects whether to unpublish vector or raster data based on
    the platform request record or explicit parameters.

    Body Options:
        Option 1 - By DDH Identifiers (Preferred):
        {
            "dataset_id": "aerial-imagery-2024",
            "resource_id": "site-alpha",
            "version_id": "v1.0",
            "dry_run": true
        }

        Option 2 - By Request ID:
        {
            "request_id": "a3f2c1b8e9d7f6a5...",
            "dry_run": true
        }

        Option 3 - By Job ID:
        {
            "job_id": "abc123...",
            "dry_run": true
        }

        Option 4 - Explicit data_type (cleanup mode):
        {
            "data_type": "vector",
            "table_name": "my_table",
            "dry_run": true
        }

    Note: dry_run=true by default (preview mode, no deletions).
    """
    from triggers.trigger_platform import platform_unpublish
    return platform_unpublish(req)


# ============================================================================
# APPROVAL ENDPOINTS (17 JAN 2026)
# ============================================================================

@bp.route(route="platform/approve", methods=["POST"])
def platform_approve_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Approve a pending dataset for publication.

    POST /api/platform/approve

    Body:
        {
            "approval_id": "apr-abc123...",  // Or stac_item_id or job_id
            "reviewer": "user@example.com",
            "notes": "Looks good"            // Optional
        }

    Response:
        {
            "success": true,
            "approval_id": "apr-abc123...",
            "status": "approved",
            "action": "stac_updated",
            "message": "Dataset approved successfully"
        }
    """
    from triggers.trigger_approvals import platform_approve
    return platform_approve(req)


@bp.route(route="platform/revoke", methods=["POST"])
def platform_revoke_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Revoke an approved dataset (unapprove).

    POST /api/platform/revoke

    This is an audit-logged operation for unpublishing approved data.

    Body:
        {
            "approval_id": "apr-abc123...",       // Or stac_item_id or job_id
            "revoker": "user@example.com",
            "reason": "Data quality issue found"  // Required for audit
        }

    Response:
        {
            "success": true,
            "approval_id": "apr-abc123...",
            "status": "revoked",
            "warning": "Approved dataset has been revoked",
            "message": "Approval revoked successfully"
        }
    """
    from triggers.trigger_approvals import platform_revoke
    return platform_revoke(req)


@bp.route(route="platform/approvals", methods=["GET"])
def platform_approvals_list_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    List approvals with optional filters.

    GET /api/platform/approvals?status=pending&limit=50

    Query Parameters:
        status: pending, approved, rejected, revoked
        classification: ouo, public
        limit: Max results (default 100)
        offset: Pagination offset

    Response:
        {
            "success": true,
            "approvals": [...],
            "count": 25,
            "status_counts": {"pending": 5, "approved": 15, ...}
        }
    """
    from triggers.trigger_approvals import platform_approvals_list
    return platform_approvals_list(req)


@bp.route(route="platform/approvals/{approval_id}", methods=["GET"])
def platform_approval_get_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get a single approval by ID.

    GET /api/platform/approvals/{approval_id}

    Response:
        {
            "success": true,
            "approval": {...}
        }
    """
    from triggers.trigger_approvals import platform_approval_get
    return platform_approval_get(req)


@bp.route(route="platform/approvals/status", methods=["GET"])
def platform_approvals_status_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get approval statuses for multiple STAC items/collections (batch lookup).

    GET /api/platform/approvals/status?stac_item_ids=item1,item2,item3
    GET /api/platform/approvals/status?stac_collection_ids=col1,col2

    Returns a map of ID -> approval status for quick UI lookups.
    Used by collection dashboards to show approved status and control delete buttons.

    Response:
        {
            "success": true,
            "statuses": {
                "item1": {"has_approval": true, "is_approved": true, ...},
                "item2": {"has_approval": false}
            }
        }
    """
    from triggers.trigger_approvals import platform_approvals_status
    return platform_approvals_status(req)


# ============================================================================
# CATALOG ENDPOINTS - B2B STAC Access (16 JAN 2026 - F12.8)
# ============================================================================

@bp.route(route="platform/catalog/lookup", methods=["GET"])
async def platform_catalog_lookup_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Lookup STAC item by DDH identifiers.

    GET /api/platform/catalog/lookup?dataset_id=X&resource_id=Y&version_id=Z

    Verifies that a STAC item exists for the given DDH identifiers.
    Returns STAC collection/item IDs and metadata if found.
    """
    from triggers.trigger_platform_catalog import platform_catalog_lookup
    return await platform_catalog_lookup(req)


@bp.route(route="platform/catalog/item/{collection_id}/{item_id}", methods=["GET"])
async def platform_catalog_item_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get full STAC item by collection and item ID.

    GET /api/platform/catalog/item/{collection_id}/{item_id}

    Returns the complete STAC item (GeoJSON Feature) with all metadata.
    """
    from triggers.trigger_platform_catalog import platform_catalog_item
    return await platform_catalog_item(req)


@bp.route(route="platform/catalog/assets/{collection_id}/{item_id}", methods=["GET"])
async def platform_catalog_assets_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get asset URLs with pre-built TiTiler visualization URLs.

    GET /api/platform/catalog/assets/{collection_id}/{item_id}

    Returns asset URLs and TiTiler URLs for visualization.
    Query param: include_titiler=false to skip TiTiler URLs.
    """
    from triggers.trigger_platform_catalog import platform_catalog_assets
    return await platform_catalog_assets(req)


@bp.route(route="platform/catalog/dataset/{dataset_id}", methods=["GET"])
async def platform_catalog_dataset_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all STAC items for a DDH dataset.

    GET /api/platform/catalog/dataset/{dataset_id}?limit=100

    Returns all STAC items with the specified platform:dataset_id.
    """
    from triggers.trigger_platform_catalog import platform_catalog_dataset
    return await platform_catalog_dataset(req)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['bp']
