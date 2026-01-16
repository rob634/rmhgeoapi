# ============================================================================
# CLAUDE CONTEXT - REDOC WEB INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - ReDoc API documentation
# PURPOSE: Package init for ReDoc interface module
# LAST_REVIEWED: 16 JAN 2026
# EXPORTS: ReDocInterface
# FEATURE: F12.8 API Documentation Hub
# ============================================================================
"""
ReDoc Web Interface package.

Provides ReDoc-based API documentation at /api/interface/redoc.
"""

from .interface import ReDocInterface

__all__ = ['ReDocInterface']
