# ============================================================================
# PLATFORM BLUEPRINT MODULE
# ============================================================================
# STATUS: Trigger layer - Platform anti-corruption layer for external apps
# PURPOSE: Centralized platform endpoints using Azure Functions Blueprint
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 5 Platform Blueprint
# ============================================================================
"""
Platform Blueprint Module.

Provides a Blueprint with all platform endpoints for external application
integration (DDH). This is the anti-corruption layer that coordinates
job requests from outside apps to our core orchestration.

Endpoints (17 total):
    Submit/Status:
        POST /platform/submit - Submit request from DDH
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

Usage in function_app.py:
    from triggers.platform import platform_bp
    if _app_mode.has_platform_endpoints:
        app.register_functions(platform_bp)

Exports:
    platform_bp: Azure Functions Blueprint with all platform endpoints
"""

from .platform_bp import bp as platform_bp

__all__ = ['platform_bp']
