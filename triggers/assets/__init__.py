# ============================================================================
# ASSET TRIGGERS PACKAGE
# ============================================================================
# STATUS: Trigger layer - Asset-centric endpoints
# PURPOSE: HTTP endpoints operating on GeospatialAsset (Aggregate Root)
# CREATED: 08 FEB 2026 (V0.8.11 - Approval Consolidation Phase 3)
# ============================================================================
"""
Asset Triggers Package.

Contains asset-centric HTTP endpoints that operate directly on GeospatialAsset.
These are the V0.8+ endpoints that treat GeospatialAsset as the Aggregate Root.

Blueprints:
    asset_approvals_bp: Approval workflow endpoints (/api/assets/{id}/approve, etc.)

V0.8.11: Initial creation as part of Approval Consolidation Phase 3.
"""

from .asset_approvals_bp import bp as asset_approvals_bp

__all__ = ['asset_approvals_bp']
