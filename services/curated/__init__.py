# ============================================================================
# CURATED DATASET SERVICES PACKAGE
# ============================================================================
# STATUS: Service layer - Package init for curated dataset services
# PURPOSE: Export services for managing curated (system-managed) datasets
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: CuratedRegistryService, WDPAHandler, wdpa_handler
# ============================================================================
"""
Curated Dataset Services Package.

Services for managing curated (system-managed) datasets.

Exports:
    CuratedRegistryService: CRUD operations for curated datasets
    WDPAHandler: Handler for WDPA data operations
"""

from .registry_service import CuratedRegistryService
from .wdpa_handler import WDPAHandler, wdpa_handler

__all__ = [
    'CuratedRegistryService',
    'WDPAHandler',
    'wdpa_handler',
]
