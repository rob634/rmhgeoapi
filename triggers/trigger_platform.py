# ============================================================================
# PLATFORM REQUEST HTTP TRIGGER - FACADE
# ============================================================================
# STATUS: Trigger layer - Re-exports from triggers/platform/ submodules
# PURPOSE: Backward-compatible facade after 27 JAN 2026 refactor
# LAST_REVIEWED: 27 JAN 2026
# EXPORTS: platform_request_submit, platform_raster_submit, platform_raster_collection_submit, platform_unpublish
# ============================================================================
"""
Platform Request HTTP Trigger - Facade Module.

This module re-exports handlers from triggers/platform/ submodules for
backward compatibility. The actual implementation has been split into:

    - triggers/platform/submit.py - Submit handlers
    - triggers/platform/unpublish.py - Unpublish handlers
    - services/platform_translation.py - DDH→CoreMachine translation
    - services/platform_job_submit.py - Job creation and queue submission

Exports:
    platform_request_submit: Generic HTTP trigger for POST /api/platform/submit
    platform_raster_submit: Raster HTTP trigger for POST /api/platform/raster
    platform_raster_collection_submit: Raster collection HTTP trigger for POST /api/platform/raster-collection
    platform_unpublish: Consolidated unpublish HTTP trigger for POST /api/platform/unpublish

Refactor History (27 JAN 2026):
    - Extracted translation logic to services/platform_translation.py
    - Extracted job submission to services/platform_job_submit.py
    - Split HTTP handlers into triggers/platform/submit.py and unpublish.py
    - Deleted deprecated endpoints (platform_unpublish_vector, platform_unpublish_raster)
    - This file reduced from 2,414 lines to ~50 lines (re-exports only)

Deleted (Phase 3 - 27 JAN 2026):
    - platform_unpublish_vector: Use platform_unpublish with data_type='vector'
    - platform_unpublish_raster: Use platform_unpublish with data_type='raster'
"""

# ============================================================================
# RE-EXPORTS FROM SUBMODULES
# ============================================================================
# These are the only exports - implementations live in triggers/platform/

from triggers.platform.submit import (
    platform_request_submit,
    platform_raster_submit,
    platform_raster_collection_submit,
)

from triggers.platform.unpublish import platform_unpublish


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'platform_request_submit',
    'platform_raster_submit',
    'platform_raster_collection_submit',
    'platform_unpublish',
]
