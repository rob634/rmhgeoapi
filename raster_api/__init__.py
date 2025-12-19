"""
Raster API Portable Module.

Provides convenience wrapper endpoints for TiTiler raster operations.
Looks up STAC items to resolve asset URLs, then proxies to TiTiler.

Endpoints:
- GET /api/raster/extract/{collection}/{item} - Extract bbox as image
- GET /api/raster/point/{collection}/{item} - Point value query
- GET /api/raster/clip/{collection}/{item} - Clip to admin boundary
- GET /api/raster/preview/{collection}/{item} - Quick preview image

Integration (in function_app.py):
    from raster_api import get_raster_triggers

    for trigger in get_raster_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

Created: 18 DEC 2025
"""

from .triggers import get_raster_triggers

__all__ = ['get_raster_triggers']
