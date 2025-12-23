# ============================================================================
# CLAUDE CONTEXT - STAC MAP INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web interface module - STAC Collections BBox Map Viewer
# PURPOSE: Display STAC collection bounding boxes on interactive Leaflet map
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: StacMapInterface
# DEPENDENCIES: web_interfaces.base, azure.functions
# ============================================================================
"""
STAC Map Interface Package.

Visualizes STAC collection spatial extents on an interactive Leaflet map.
"""

from .interface import StacMapInterface

__all__ = ['StacMapInterface']
