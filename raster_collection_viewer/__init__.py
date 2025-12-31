"""
Raster Collection Viewer - STAC-Integrated Raster Map Viewer.

Feature: F2.9 (30 DEC 2025)

Provides interactive Leaflet-based viewer for browsing STAC raster collections
with smart TiTiler URL generation based on raster metadata (app:* properties).

Exports:
    RasterCollectionViewerService: Service for generating viewer HTML
    get_raster_collection_viewer_triggers: Returns trigger configurations for route registration
"""

from raster_collection_viewer.service import RasterCollectionViewerService
from raster_collection_viewer.triggers import get_raster_collection_viewer_triggers

__all__ = [
    'RasterCollectionViewerService',
    'get_raster_collection_viewer_triggers'
]
