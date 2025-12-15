"""
Curated Dataset Services Package.

Services for managing curated (system-managed) datasets.

Exports:
    CuratedRegistryService: CRUD operations for curated datasets
"""

from .registry_service import CuratedRegistryService

__all__ = [
    'CuratedRegistryService',
]
