# ============================================================================
# CLAUDE CONTEXT - RASTER VIEWER INTERFACE MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - TiTiler Raster Viewer
# PURPOSE: Leaflet interface for COG preview with RGB band selection
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: RasterViewerInterface
# DEPENDENCIES: azure.functions, web_interfaces.base
# ============================================================================
"""
Raster Viewer interface module.

Exports the RasterViewerInterface class for registration.
"""

from web_interfaces.raster_viewer.interface import RasterViewerInterface

__all__ = ['RasterViewerInterface']
