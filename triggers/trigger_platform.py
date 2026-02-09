# ============================================================================
# PLATFORM REQUEST HTTP TRIGGER - FACADE
# ============================================================================
# STATUS: Trigger layer - Re-exports from triggers/platform/ submodules
# PURPOSE: Backward-compatible facade after 27 JAN 2026 refactor
# LAST_REVIEWED: 09 FEB 2026
# EXPORTS: platform_request_submit, platform_unpublish
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
    platform_unpublish: Consolidated unpublish HTTP trigger for POST /api/platform/unpublish

Refactor History:
    27 JAN 2026:
        - Extracted translation logic to services/platform_translation.py
        - Extracted job submission to services/platform_job_submit.py
        - Split HTTP handlers into triggers/platform/submit.py and unpublish.py
        - This file reduced from 2,414 lines to ~50 lines (re-exports only)

    09 FEB 2026:
        - Removed deprecated endpoint exports (platform_raster_submit, platform_raster_collection_submit)
        - All submissions now use unified /api/platform/submit endpoint
        - Deprecated routes return 410 Gone (handlers in platform_bp.py)
"""

# ============================================================================
# RE-EXPORTS FROM SUBMODULES
# ============================================================================
# These are the only exports - implementations live in triggers/platform/

from triggers.platform.submit import platform_request_submit
from triggers.platform.unpublish import platform_unpublish


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'platform_request_submit',
    'platform_unpublish',
]
