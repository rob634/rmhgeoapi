# ============================================================================
# OGC FEATURES API MODULE
# ============================================================================
# STATUS: API module - Self-contained OGC API Features implementation
# PURPOSE: OGC API - Features Core 1.0 compliant endpoints for PostGIS data
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: OGCFeaturesConfig, OGCFeaturesService, get_ogc_triggers
# DEPENDENCIES: pydantic, psycopg, azure.functions
# ============================================================================
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

# triggers import is DEFERRED — it pulls in azure.functions which is not
# available on Docker workers. Import get_ogc_triggers explicitly where needed.
# from .triggers import get_ogc_triggers  # REMOVED from module level (21 MAR 2026)

__version__ = "1.0.0"
__all__ = [
    "OGCFeaturesConfig",
    "OGCFeaturesService",
]
