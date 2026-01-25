# ============================================================================
# STAC BLUEPRINT MODULE
# ============================================================================
# STATUS: Trigger layer - Unified STAC API & Admin Blueprint
# PURPOSE: All stac/* endpoints in one blueprint
# CREATED: 24 JAN 2026 (V0.8 Phase 17.3)
# EXPORTS: stac_bp
# ============================================================================
"""
STAC Blueprint Module - Unified STAC API & Admin Endpoints.

Exports:
    stac_bp: Azure Functions Blueprint with all 19 stac/* routes

Routes (19 total):
    STAC API v1.0.0 Core (6):
        GET  /stac, /stac/conformance, /stac/collections, etc.

    Admin - Initialization (3):
        POST /stac/init, /stac/collections/{tier}, /stac/nuke

    Admin - Repair (3):
        GET/POST /stac/repair/*

    Admin - Catalog Operations (2):
        POST /stac/extract, /stac/vector

    Admin - Inspection (5):
        GET /stac/schema/info, /stac/collections/summary, etc.
"""

from .stac_bp import bp as stac_bp

__all__ = ['stac_bp']
