# ============================================================================
# CLAUDE CONTEXT - VECTOR VIEWER MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Standalone Module - Vector Data QA Viewer (OGC Features API)
# PURPOSE: Self-contained vector viewer for data curator validation
# LAST_REVIEWED: 13 NOV 2025
# EXPORTS: VectorViewerService, get_vector_viewer_triggers
# INTERFACES: Standalone - no dependencies on main application
# PYDANTIC_MODELS: None (simple HTML generation)
# DEPENDENCIES: requests, json, azure-functions (standalone)
# SOURCE: OGC Features API endpoints (/api/features/collections/{id})
# SCOPE: Standalone vector viewer - portable to any Function App
# VALIDATION: Query parameter validation
# PATTERNS: Service Layer, Standalone Module
# ENTRY_POINTS: from vector_viewer import get_vector_viewer_triggers
# INDEX: Exports:35
# ============================================================================

"""
Vector Viewer - Standalone Module (OGC Features API)

A self-contained vector feature viewer for data curators to validate
vector ETL output. Generates dynamic HTML pages with Leaflet maps showing
individual PostGIS collections.

Use Case:
- Data curator runs vector ETL process
- PostGIS table is created in geo schema
- Curator opens preview link to visually validate geometry and metadata
- Quick QA: "Does the geometry look right? Is it in the correct location?"

Features:
- Minimal Leaflet map with OSM basemap
- Vector features rendered as GeoJSON
- Metadata panel (collection ID, bbox, feature count)
- Auto-zoom to feature bounds
- Self-contained HTML (no separate CSS/JS files)

Architecture:
    vector_viewer/
    ├── __init__.py    # Module exports
    ├── service.py     # HTML generation and OGC Features API calls
    └── triggers.py    # Azure Functions HTTP handler

Integration:
    # In function_app.py (ONLY integration point)
    from vector_viewer import get_vector_viewer_triggers

    for trigger in get_vector_viewer_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

Usage:
    GET /api/vector/viewer?collection={collection_id}

    Example:
    https://rmhazuregeoapi-.../api/vector/viewer?collection=qa_test_chunk_5000

Deployment:
    1. Copy vector_viewer/ folder to Function App
    2. Deploy: func azure functionapp publish <app-name>

"""

from .service import VectorViewerService
from .triggers import get_vector_viewer_triggers

__version__ = "1.0.0"
__all__ = [
    "VectorViewerService",
    "get_vector_viewer_triggers"
]
