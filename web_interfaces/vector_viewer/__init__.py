# ============================================================================
# CLAUDE CONTEXT - VECTOR VIEWER WEB INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Vector Collection QA Viewer
# PURPOSE: MapLibre/Leaflet interface for vector data QA with approve/reject
# CREATED: 07 FEB 2026 (moved from vector_viewer/)
# EXPORTS: VectorViewerInterface
# DEPENDENCIES: azure.functions, web_interfaces.base
# ============================================================================
"""
Vector Viewer Web Interface.

Moved from /vector_viewer/ to /web_interfaces/vector_viewer/ on 07 FEB 2026
to consolidate all UI under /api/interface/* pattern.

Route: /api/interface/vector-viewer?collection={collection_id}
"""

from .interface import VectorViewerInterface

__all__ = ['VectorViewerInterface']
