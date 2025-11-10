"""
STAC API Portable Module

Provides STAC API v1.0.0 compliant endpoints as a fully portable module.
Can be deployed standalone or integrated into existing Function App.

Integration (in function_app.py):
    from stac_api import get_stac_triggers

    for trigger in get_stac_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
"""

from .triggers import get_stac_triggers

__all__ = ['get_stac_triggers']
