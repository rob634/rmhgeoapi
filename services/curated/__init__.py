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
