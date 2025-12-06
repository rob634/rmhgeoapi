"""
OGC Features API module.

Self-contained OGC API - Features Core 1.0 implementation for PostGIS vector data.

Exports:
    OGCFeaturesService: Business logic orchestration for OGC Features API
    OGCFeaturesConfig: Environment-based configuration management
    get_ogc_triggers: Azure Functions HTTP trigger configurations
"""

from .config import OGCFeaturesConfig
from .service import OGCFeaturesService
from .triggers import get_ogc_triggers

__version__ = "1.0.0"
__all__ = [
    "OGCFeaturesConfig",
    "OGCFeaturesService",
    "get_ogc_triggers"
]
