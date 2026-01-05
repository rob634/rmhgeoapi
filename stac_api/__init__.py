# ============================================================================
# STAC API MODULE
# ============================================================================
# STATUS: API module - STAC API v1.0.0 compliant portable module
# PURPOSE: Self-contained STAC API endpoints for pgSTAC data
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: get_stac_triggers
# DEPENDENCIES: infrastructure.pgstac_bootstrap, azure.functions
# ============================================================================
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

"""

from .triggers import get_stac_triggers

__all__ = ['get_stac_triggers']
