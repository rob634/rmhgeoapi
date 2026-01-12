# ============================================================================
# CLAUDE CONTEXT - INTEGRATION WEB INTERFACE PACKAGE
# ============================================================================
# STATUS: Web Interface Package - DDH App Integration Guides
# PURPOSE: Step-by-step integration guides for external applications
# CREATED: 12 JAN 2026
# EXPORTS: IntegrationInterface, ProcessRasterIntegrationInterface
# DEPENDENCIES: web_interfaces.base
# ============================================================================
"""
Integration Guide web interface package.

Provides step-by-step integration guides for DDH App and other external
applications to interact with the GeoAPI.

Interfaces:
    - integration: Landing page with links to all integration guides
    - integration-process-raster: Process Raster V2 integration guide
"""

from .interface import IntegrationInterface, ProcessRasterIntegrationInterface

__all__ = ['IntegrationInterface', 'ProcessRasterIntegrationInterface']
