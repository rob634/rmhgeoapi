# ============================================================================
# CLAUDE CONTEXT - OGC FEATURES API MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Standalone Module - OGC Features API implementation
# PURPOSE: Self-contained OGC API - Features implementation for PostGIS vector data
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: OGCFeaturesService, OGCFeaturesConfig, get_ogc_triggers
# INTERFACES: Standalone - no dependencies on main application
# PYDANTIC_MODELS: OGCFeatureCollection, OGCCollection, OGCLandingPage
# DEPENDENCIES: psycopg, pydantic, azure-functions (standalone)
# SOURCE: Environment variables for PostGIS connection
# SCOPE: Standalone OGC Features API - portable to any Function App
# VALIDATION: Pydantic models, query parameter validation
# PATTERNS: Service Layer, Repository Pattern, Standalone Module
# ENTRY_POINTS: from ogc_features import get_ogc_triggers
# INDEX: Exports:35
# ============================================================================

"""
OGC Features API - Standalone Module

A completely self-contained implementation of OGC API - Features Core specification
for serving PostGIS vector data via HTTP. This module has ZERO dependencies on the
main application and can be deployed independently.

Features:
- OGC API - Features Core 1.0 compliance
- PostGIS ST_AsGeoJSON with simplification/quantization
- Spatial index optimization
- Configurable geometry simplification
- Support for "geom" and "shape" columns (ArcGIS compatibility)
- Standalone configuration and database connections

Architecture:
    ogc_features/
    ├── config.py      # Environment-based configuration
    ├── models.py      # Pydantic models (OGC responses)
    ├── repository.py  # PostGIS direct access (psycopg)
    ├── service.py     # Business logic layer
    ├── triggers.py    # Azure Functions HTTP handlers
    └── README.md      # Deployment guide

Integration:
    # In function_app.py (ONLY integration point)
    from ogc_features import get_ogc_triggers

    for trigger in get_ogc_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

Deployment:
    1. Copy ogc_features/ folder to new Function App
    2. Set environment variables (POSTGIS_HOST, etc.)
    3. Deploy: func azure functionapp publish <app-name>

Author: Robert and Geospatial Claude Legion
Date: 29 OCT 2025
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
