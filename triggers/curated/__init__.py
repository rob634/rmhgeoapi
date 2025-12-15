"""
Curated Dataset Triggers Package.

HTTP and timer triggers for curated dataset management.

Exports:
    curated_admin_trigger: HTTP trigger for CRUD operations
"""

from .admin import curated_admin_trigger

__all__ = [
    'curated_admin_trigger',
]
