# ============================================================================
# CLAUDE CONTEXT - OGC API STYLES MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: New module - OGC API Styles implementation
# PURPOSE: Store CartoSym-JSON styles and serve multi-format output
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: StyleTranslator, OGCStylesRepository, OGCStylesService
# DEPENDENCIES: psycopg, pydantic
# ============================================================================
"""
OGC API Styles Module.

Provides server-side style management for OGC Features collections:
- Store styles in CartoSym-JSON (OGC standard format)
- Serve styles in multiple output formats (Leaflet, Mapbox GL)
- Content negotiation via Accept header or ?f= parameter

Endpoints:
    GET /features/collections/{id}/styles        - List styles
    GET /features/collections/{id}/styles/{sid}  - Get style (multi-format)

Usage:
    from ogc_styles import OGCStylesService

    service = OGCStylesService()
    styles = service.list_styles("my_collection", base_url)
    style, content_type = service.get_style("my_collection", "default", "leaflet")

Created: 18 DEC 2025
"""

from .translator import StyleTranslator
from .repository import OGCStylesRepository
from .service import OGCStylesService
from .triggers import get_styles_triggers

__all__ = [
    "StyleTranslator",
    "OGCStylesRepository",
    "OGCStylesService",
    "get_styles_triggers",
]
