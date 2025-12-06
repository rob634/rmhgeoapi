"""
Vector viewer module.

Self-contained vector feature viewer for data curator validation with Leaflet maps.

Exports:
    VectorViewerService: HTML generation and OGC Features API integration
    get_vector_viewer_triggers: Azure Functions HTTP trigger configurations
"""

from .service import VectorViewerService
from .triggers import get_vector_viewer_triggers

__version__ = "1.0.0"
__all__ = [
    "VectorViewerService",
    "get_vector_viewer_triggers"
]
