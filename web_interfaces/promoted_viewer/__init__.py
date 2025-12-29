# ============================================================================
# CLAUDE CONTEXT - PROMOTED DATASET VIEWER MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Styled map viewer for promoted datasets
# PURPOSE: Display promoted vector datasets with OGC Styles applied
# LAST_REVIEWED: 29 DEC 2025
# EXPORTS: PromotedViewerInterface
# DEPENDENCIES: web_interfaces.base, ogc_styles
# ============================================================================
"""
Promoted Dataset Viewer module.

Full-featured map viewer for promoted datasets with OGC Style rendering.
Fetches promoted metadata and style, displays styled features with controls.

Exports the PromotedViewerInterface class for registration.
"""

from web_interfaces.promoted_viewer.interface import PromotedViewerInterface

__all__ = ['PromotedViewerInterface']
