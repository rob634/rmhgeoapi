# ============================================================================
# CURATED DATASET TRIGGERS PACKAGE
# ============================================================================
# STATUS: Trigger layer - Package init for curated dataset triggers
# PURPOSE: Export HTTP and timer triggers for curated dataset management
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: curated_admin_trigger, curated_scheduler_trigger
# ============================================================================
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
