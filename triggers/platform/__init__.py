# ============================================================================
# PLATFORM BLUEPRINT MODULE
# ============================================================================
# STATUS: Trigger layer - Platform anti-corruption layer for external apps
# PURPOSE: Centralized platform endpoints using Azure Functions Blueprint
# CREATED: 23 JAN 2026
# UPDATED: 09 FEB 2026 - Removed deprecated raster endpoint re-exports
# EPIC: APP_CLEANUP - Phase 5 Platform Blueprint
# ============================================================================
"""
Platform Blueprint Module.

Provides a Blueprint with all platform endpoints for external application
integration (DDH). This is the anti-corruption layer that coordinates
job requests from outside apps to our core orchestration.

Endpoints (17 total):
    Submit/Status:
        POST /platform/submit - Submit request from DDH (unified endpoint)
        GET  /platform/status/{id} - Get request/job status
        GET  /platform/status - List all requests

    Diagnostics:
        GET  /platform/health - System readiness
        GET  /platform/failures - Recent failures
        GET  /platform/lineage/{id} - Data lineage trace
        POST /platform/validate - Pre-flight validation

    Unpublish:
        POST /platform/unpublish - Consolidated unpublish

    Approvals:
        POST /platform/approve - Approve dataset
        POST /platform/revoke - Revoke approval
        GET  /platform/approvals - List approvals
        GET  /platform/approvals/{id} - Get approval
        GET  /platform/approvals/status - Batch status lookup

    Catalog:
        GET  /platform/catalog/lookup - STAC lookup by DDH IDs
        GET  /platform/catalog/item/{c}/{i} - Get STAC item
        GET  /platform/catalog/assets/{c}/{i} - Get assets
        GET  /platform/catalog/dataset/{id} - List items for dataset

    Deprecated (return 410 Gone):
        POST /platform/raster - Use /platform/submit instead
        POST /platform/raster-collection - Use /platform/submit instead
        POST /platform/vector - Use /platform/submit instead

Usage in function_app.py:
    from triggers.platform import platform_bp
    if _app_mode.has_platform_endpoints:
        app.register_functions(platform_bp)

Exports:
    platform_bp: Azure Functions Blueprint with all platform endpoints

Handler Re-exports:
    platform_request_submit: Generic submit handler
    platform_unpublish: Consolidated unpublish handler
"""

from .platform_bp import bp as platform_bp

# Re-export handlers (09 FEB 2026 - removed deprecated raster handlers)
from .submit import platform_request_submit
from .unpublish import platform_unpublish

__all__ = [
    'platform_bp',
    # Handler re-exports
    'platform_request_submit',
    'platform_unpublish',
]
