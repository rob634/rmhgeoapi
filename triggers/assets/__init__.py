# ============================================================================
# ASSET TRIGGERS PACKAGE
# ============================================================================
# STATUS: Trigger layer - Asset-centric endpoints (V0.9 Release-based)
# PURPOSE: HTTP endpoints for Asset approval workflow (resolves to AssetRelease)
# CREATED: 08 FEB 2026 (V0.8.11 - Approval Consolidation Phase 3)
# LAST_REVIEWED: 21 FEB 2026 (V0.9 Asset/Release entity split)
# ============================================================================
"""
Asset Triggers Package.

Contains asset-centric HTTP endpoints. URLs use asset_id for API stability,
but internally resolve to release_id and operate on AssetRelease.

Blueprints:
    asset_approvals_bp: Approval workflow endpoints (/api/assets/{id}/approve, etc.)

V0.9: Migrated from GeospatialAsset to Asset + AssetRelease entity split.
"""

from .asset_approvals_bp import bp as asset_approvals_bp

__all__ = ['asset_approvals_bp']
