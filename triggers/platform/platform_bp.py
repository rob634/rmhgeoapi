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
    2. Diagnostics - Health, failures
    3. Data Diagnostics - Stats, geo integrity, lineage (B2B visibility)
    4. Unpublish - Consolidated data removal
    5. Approvals - Dataset approval workflow
    6. Catalog - B2B unified asset access
"""

import azure.functions as func

from services.platform_response import check_accept_header
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "PlatformBlueprint")

# Create Blueprint
bp = func.Blueprint()


# ============================================================================
# CACHE HEADER HELPER (ADV-20)
# ============================================================================

def _with_cache(response: func.HttpResponse, success_policy: str) -> func.HttpResponse:
    """Add Cache-Control header. Errors (4xx/5xx) always get no-store."""
    if response.status_code >= 400:
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = success_policy
    return response


# ============================================================================
# API ROUTE MANIFEST
# ============================================================================

_ROUTE_MANIFEST = {
    "submit_and_status": {
        "description": "Submit datasets for ETL processing and monitor status",
        "endpoints": [
            {"method": "POST", "path": "/api/platform/submit", "description": "Submit a dataset for ETL processing"},
            {"method": "GET", "path": "/api/platform/status", "description": "List all processing requests", "params": ["limit", "offset", "dataset_id"]},
            {"method": "GET", "path": "/api/platform/status/{id}", "description": "Lookup by request_id, job_id, release_id, or asset_id"},
            {"method": "GET", "path": "/api/platform/status?dataset_id=X&resource_id=Y", "description": "Lookup by platform identifiers"},
            {"method": "POST", "path": "/api/platform/resubmit", "description": "Retry a failed request with cleanup"},
            {"method": "POST", "path": "/api/platform/unpublish", "description": "Remove published data"},
        ],
    },
    "approvals": {
        "description": "Dataset approval workflow (submit -> pending_review -> approved/rejected -> revoked)",
        "endpoints": [
            {"method": "GET", "path": "/api/platform/approvals", "description": "List approvals", "params": ["status", "limit", "offset"]},
            {"method": "GET", "path": "/api/platform/approvals/{id}", "description": "Get single approval"},
            {"method": "GET", "path": "/api/platform/approvals/status", "description": "Batch approval status lookup", "params": ["stac_item_ids", "stac_collection_ids"]},
            {"method": "POST", "path": "/api/platform/approve", "description": "Approve a pending release"},
            {"method": "POST", "path": "/api/platform/reject", "description": "Reject a pending release"},
            {"method": "POST", "path": "/api/platform/revoke", "description": "Revoke an approved release"},
        ],
    },
    "catalog": {
        "description": "Discover and access published assets",
        "endpoints": [
            {"method": "GET", "path": "/api/platform/catalog/lookup", "description": "Lookup by DDH identifiers", "params": ["dataset_id", "resource_id", "version_id"]},
            {"method": "GET", "path": "/api/platform/catalog/asset/{asset_id}", "description": "Asset detail with service URLs"},
            {"method": "GET", "path": "/api/platform/catalog/item/{collection_id}/{item_id}", "description": "Full STAC item"},
            {"method": "GET", "path": "/api/platform/catalog/assets/{collection_id}/{item_id}", "description": "Asset URLs with TiTiler visualization"},
            {"method": "GET", "path": "/api/platform/catalog/dataset/{dataset_id}", "description": "List all assets for a dataset", "params": ["limit", "offset"]},
        ],
    },
    "diagnostics": {
        "description": "System health, data visibility, and failure monitoring",
        "endpoints": [
            {"method": "GET", "path": "/api/platform/health", "description": "System readiness check"},
            {"method": "GET", "path": "/api/platform/failures", "description": "Recent failures with sanitized errors", "params": ["hours", "limit"]},
            {"method": "GET", "path": "/api/platform/diagnostics/stats", "description": "Table row counts and activity"},
            {"method": "GET", "path": "/api/platform/diagnostics/geo_integrity", "description": "Geo schema and TiPG sync health"},
            {"method": "GET", "path": "/api/platform/diagnostics/lineage/{job_id}", "description": "ETL lineage trace for a job"},
        ],
    },
    "registry": {
        "description": "Platform configuration and metadata",
        "endpoints": [
            {"method": "GET", "path": "/api/platform/registry", "description": "List supported B2B platforms", "params": ["active_only"]},
            {"method": "GET", "path": "/api/platform/registry/{platform_id}", "description": "Platform detail"},
        ],
    },
}


@bp.route(route="platform", methods=["GET"])
def platform_route_manifest(req: func.HttpRequest) -> func.HttpResponse:
    """
    API route manifest — lists all available platform endpoints.

    GET /api/platform
    """
    import json
    from config import __version__
    from datetime import datetime, timezone

    return func.HttpResponse(
        json.dumps({
            "service": "DDHGeo ETL Orchestrator",
            "version": __version__,
            "base_path": "/api/platform",
            "endpoints": _ROUTE_MANIFEST,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, indent=2),
        status_code=200,
        headers={
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=300",
        },
    )


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
            "title": "Landsat 8 Scene",
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
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform import platform_request_submit
    return _with_cache(platform_request_submit(req), "no-store")


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
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_status import platform_request_status
    return _with_cache(await platform_request_status(req), "private, no-cache")


@bp.route(route="platform/status", methods=["GET"])
async def platform_status_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all platform requests.

    GET /api/platform/status?limit=100&status=pending

    Returns list of all platform requests with optional filtering.
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_status import platform_request_status
    return _with_cache(await platform_request_status(req), "private, no-cache")


# ============================================================================
# PLATFORM REGISTRY ENDPOINTS (V0.8 - 29 JAN 2026)
# ============================================================================

@bp.route(route="platform/registry", methods=["GET"])
def platforms_list_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all supported B2B platforms.

    GET /api/platform/registry

    Returns list of platforms with their identifier requirements.
    Used by B2B clients to understand what identifiers are needed for each platform.

    Query Parameters:
        active_only: If "false", include inactive platforms (default: true)

    Response:
        {
            "success": true,
            "platforms": [
                {
                    "platform_id": "ddh",
                    "display_name": "Data Distribution Hub",
                    "description": "Primary B2B platform with dataset/resource/version hierarchy",
                    "required_refs": ["dataset_id", "resource_id", "version_id"],
                    "optional_refs": ["title", "description", "access_level"],
                    "is_active": true
                }
            ],
            "count": 1
        }
    """
    if (reject := check_accept_header(req)):
        return reject

    import json

    try:
        from infrastructure import PlatformRegistryRepository

        # Parse query params
        active_only = req.params.get("active_only", "true").lower() != "false"

        repo = PlatformRegistryRepository()
        platforms = repo.list_all(active_only=active_only)

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "platforms": [
                    {
                        "platform_id": p.platform_id,
                        "display_name": p.display_name,
                        "description": p.description,
                        "required_refs": p.required_refs,
                        "optional_refs": p.optional_refs,
                        "is_active": p.is_active
                    }
                    for p in platforms
                ],
                "count": len(platforms)
            }),
            status_code=200,
            headers={"Content-Type": "application/json", "Cache-Control": "private, max-age=300"}
        )
    except Exception as e:
        logger.error(f"Failed to list platforms: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json", "Cache-Control": "no-store"}
        )


@bp.route(route="platform/registry/{platform_id}", methods=["GET"])
def platform_get_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get details of a specific platform.

    GET /api/platform/registry/{platform_id}

    Path Parameters:
        platform_id: Platform identifier (e.g., "ddh")

    Response:
        {
            "success": true,
            "platform": {
                "platform_id": "ddh",
                "display_name": "Data Distribution Hub",
                "description": "Primary B2B platform...",
                "required_refs": ["dataset_id", "resource_id", "version_id"],
                "optional_refs": ["title", "description"],
                "is_active": true
            }
        }
    """
    if (reject := check_accept_header(req)):
        return reject

    import json

    try:
        from infrastructure import PlatformRegistryRepository

        platform_id = req.route_params.get("platform_id")
        if not platform_id:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "platform_id is required",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json", "Cache-Control": "no-store"}
            )

        repo = PlatformRegistryRepository()
        platform = repo.get(platform_id)

        if not platform:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Platform not found: {platform_id}",
                    "error_type": "NotFound"
                }),
                status_code=404,
                headers={"Content-Type": "application/json", "Cache-Control": "no-store"}
            )

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "platform": {
                    "platform_id": platform.platform_id,
                    "display_name": platform.display_name,
                    "description": platform.description,
                    "required_refs": platform.required_refs,
                    "optional_refs": platform.optional_refs,
                    "is_active": platform.is_active
                }
            }),
            status_code=200,
            headers={"Content-Type": "application/json", "Cache-Control": "private, max-age=300"}
        )
    except Exception as e:
        logger.error(f"Failed to get platform: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json", "Cache-Control": "no-store"}
        )


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
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_status import platform_health
    return _with_cache(await platform_health(req), "private, no-cache")


@bp.route(route="platform/failures", methods=["GET"])
async def platform_failures_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Recent failures with sanitized error summaries.

    GET /api/platform/failures?hours=24&limit=20

    Returns failure patterns and recent failures with sanitized messages
    (no internal paths, secrets, or stack traces).
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_status import platform_failures
    return _with_cache(await platform_failures(req), "private, no-cache")


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
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform import platform_unpublish
    return _with_cache(platform_unpublish(req), "no-store")


# ============================================================================
# RESUBMIT ENDPOINT (30 JAN 2026)
# ============================================================================

@bp.route(route="platform/resubmit", methods=["POST"])
def platform_resubmit_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Resubmit a failed job with cleanup.

    POST /api/platform/resubmit

    Cleans up all artifacts from a failed job and resubmits with the same
    parameters. Useful for retrying failed jobs from external applications.

    Body Options:
        Option 1 - By DDH Identifiers (Preferred):
        {
            "dataset_id": "aerial-imagery-2024",
            "resource_id": "site-alpha",
            "version_id": "v1.0",
            "dry_run": false,
            "delete_blobs": false
        }

        Option 2 - By Request ID:
        {
            "request_id": "a3f2c1b8e9d7f6a5...",
            "dry_run": false
        }

        Option 3 - By Job ID:
        {
            "job_id": "abc123...",
            "dry_run": false
        }

    Options:
        dry_run: Preview cleanup without executing (default: false)
        delete_blobs: Also delete COG files from storage (default: false)
        force: Resubmit even if job is currently processing (default: false)

    Response:
        {
            "success": true,
            "original_job_id": "abc123...",
            "new_job_id": "def456...",
            "job_type": "process_raster_v2",
            "platform_refs": {
                "request_id": "...",
                "dataset_id": "...",
                "resource_id": "...",
                "version_id": "..."
            },
            "cleanup_summary": {
                "tasks_deleted": 5,
                "job_deleted": true,
                "tables_dropped": [],
                "stac_items_deleted": ["item-123"],
                "blobs_deleted": []
            },
            "message": "Job resubmitted successfully",
            "monitor_url": "/api/platform/status/a3f2c1b8..."
        }
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.platform.resubmit import platform_resubmit
    return _with_cache(platform_resubmit(req), "no-store")


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
            "notes": "Looks good",           // Optional
            "dry_run": true                  // Optional: preview without executing
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
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_approvals import platform_approve
    return _with_cache(platform_approve(req), "no-store")


@bp.route(route="platform/reject", methods=["POST"])
def platform_reject_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Reject a pending dataset (V0.8 - 29 JAN 2026).

    POST /api/platform/reject

    Rejects a pending dataset that is not suitable for publication.
    This is for datasets that fail review (unlike revoke, which is for
    already-approved datasets).

    Body:
        {
            "approval_id": "apr-abc123...",       // Or stac_item_id, job_id, request_id
            "reviewer": "user@example.com",
            "reason": "Data quality issue found", // Required for audit
            "dry_run": true                       // Optional: preview without executing
        }

    Response:
        {
            "success": true,
            "approval_id": "apr-abc123...",
            "status": "rejected",
            "asset_id": "...",
            "asset_updated": true,
            "message": "Dataset rejected"
        }
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_approvals import platform_reject
    return _with_cache(platform_reject(req), "no-store")


@bp.route(route="platform/revoke", methods=["POST"])
def platform_revoke_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Revoke an approved dataset (unapprove).

    POST /api/platform/revoke

    This is an audit-logged operation for unpublishing approved data.
    V0.8: Also soft-deletes the GeospatialAsset.

    Body:
        {
            "approval_id": "apr-abc123...",       // Or stac_item_id or job_id
            "revoker": "user@example.com",
            "reason": "Data quality issue found", // Required for audit
            "dry_run": true                       // Optional: preview without executing
        }

    Response:
        {
            "success": true,
            "approval_id": "apr-abc123...",
            "status": "revoked",
            "asset_id": "...",
            "asset_deleted": true,
            "warning": "Approved dataset has been revoked",
            "message": "Approval revoked successfully"
        }
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_approvals import platform_revoke
    return _with_cache(platform_revoke(req), "no-store")


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
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_approvals import platform_approvals_list
    return _with_cache(platform_approvals_list(req), "private, no-cache")


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
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_approvals import platform_approval_get
    return _with_cache(platform_approval_get(req), "private, no-cache")


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
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_approvals import platform_approvals_status
    return _with_cache(platform_approvals_status(req), "private, no-cache")


# ============================================================================
# DIAGNOSTICS ENDPOINTS - B2B Data Visibility (21 MAR 2026)
# ============================================================================
# Subset of dbadmin/diagnostics promoted to platform/* for B2B clients.
# Clients need: "is my data there?" (stats), "is it queryable?" (geo_integrity),
# and "what happened to my submission?" (lineage).

@bp.route(route="platform/diagnostics/stats", methods=["GET"])
def platform_diagnostics_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Database table statistics for B2B visibility.

    GET /api/platform/diagnostics/stats

    Returns table row counts, insert/update/delete activity, and recent
    activity summary. Allows B2B clients to verify their data landed.
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.admin.db_diagnostics import admin_db_diagnostics_trigger
    return _with_cache(admin_db_diagnostics_trigger._get_stats(req), "private, no-cache")


@bp.route(route="platform/diagnostics/geo_integrity", methods=["GET"])
def platform_diagnostics_geo_integrity(req: func.HttpRequest) -> func.HttpResponse:
    """
    Geo schema integrity and TiPG sync validation.

    GET /api/platform/diagnostics/geo_integrity

    Returns health status of geo tables, TiPG compatibility, and sync state.
    Allows B2B clients to verify their published data is queryable via
    OGC Features API.
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.admin.db_diagnostics import admin_db_diagnostics_trigger
    return _with_cache(admin_db_diagnostics_trigger._get_geo_integrity(req), "private, no-cache")


@bp.route(route="platform/diagnostics/lineage/{job_id}", methods=["GET"])
def platform_diagnostics_lineage(req: func.HttpRequest) -> func.HttpResponse:
    """
    ETL lineage trace for a job.

    GET /api/platform/diagnostics/lineage/{job_id}

    Returns the full data lineage: source -> processing -> destination -> STAC.
    Allows B2B clients to trace what happened to their submission.
    """
    if (reject := check_accept_header(req)):
        return reject
    job_id = req.route_params.get("job_id")
    if not job_id:
        import json
        return func.HttpResponse(
            json.dumps({"success": False, "error": "job_id is required"}),
            status_code=400,
            mimetype="application/json",
        )
    from triggers.admin.db_diagnostics import admin_db_diagnostics_trigger
    return _with_cache(admin_db_diagnostics_trigger._get_etl_lineage(req, job_id), "private, no-cache")


# ============================================================================
# CATALOG ENDPOINTS - B2B Unified Access (10 FEB 2026 - UNIFIED_B2B_CATALOG)
# ============================================================================
# V0.8 UNIFIED: These endpoints now query app.geospatial_assets directly
# (source of truth), bypassing STAC and OGC Features APIs.
# Works for BOTH rasters and vectors.

@bp.route(route="platform/catalog/lookup", methods=["GET"])
async def platform_catalog_lookup_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unified lookup by DDH identifiers - works for BOTH raster and vector.

    GET /api/platform/catalog/lookup?dataset_id=X&resource_id=Y&version_id=Z

    V0.8 UNIFIED (10 FEB 2026): Queries app.geospatial_assets directly.
    Returns asset details with bbox and appropriate service URLs.
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_catalog import platform_catalog_lookup
    return _with_cache(await platform_catalog_lookup(req), "private, max-age=60")


@bp.route(route="platform/catalog/asset/{asset_id}", methods=["GET"])
async def platform_catalog_asset_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get asset details and service URLs by asset_id.

    GET /api/platform/catalog/asset/{asset_id}

    V0.8 UNIFIED (10 FEB 2026): New endpoint for direct asset lookup.
    Returns asset details with appropriate service URLs based on data_type.
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_catalog import platform_catalog_asset_by_id
    return _with_cache(await platform_catalog_asset_by_id(req), "private, max-age=60")


@bp.route(route="platform/catalog/item/{collection_id}/{item_id}", methods=["GET"])
async def platform_catalog_item_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get full STAC item by collection and item ID.

    GET /api/platform/catalog/item/{collection_id}/{item_id}

    Returns the complete STAC item (GeoJSON Feature) with all metadata.
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_catalog import platform_catalog_item
    return _with_cache(await platform_catalog_item(req), "private, max-age=60")


@bp.route(route="platform/catalog/assets/{collection_id}/{item_id}", methods=["GET"])
async def platform_catalog_assets_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get asset URLs with pre-built TiTiler visualization URLs.

    GET /api/platform/catalog/assets/{collection_id}/{item_id}

    Returns asset URLs and TiTiler URLs for visualization.
    Query param: include_titiler=false to skip TiTiler URLs.
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_catalog import platform_catalog_assets
    return _with_cache(await platform_catalog_assets(req), "private, max-age=60")


@bp.route(route="platform/catalog/dataset/{dataset_id}", methods=["GET"])
async def platform_catalog_dataset_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all assets for a DDH dataset - works for BOTH raster and vector.

    GET /api/platform/catalog/dataset/{dataset_id}?limit=100&offset=0

    V0.8 UNIFIED (10 FEB 2026): Queries app.geospatial_assets directly.
    Returns all assets (rasters AND vectors) for the specified dataset.
    """
    if (reject := check_accept_header(req)):
        return reject
    from triggers.trigger_platform_catalog import platform_catalog_dataset
    return _with_cache(await platform_catalog_dataset(req), "private, max-age=60")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['bp']
