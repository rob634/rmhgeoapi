"""
Curated Dataset Triggers Package.

HTTP and timer triggers for curated dataset management.

Exports:
    curated_admin_trigger: HTTP trigger for CRUD operations
    curated_scheduler_trigger: Timer trigger for daily updates
"""

from .admin import curated_admin_trigger
from .scheduler import curated_scheduler_trigger

__all__ = [
    'curated_admin_trigger',
    'curated_scheduler_trigger',
]
