# ============================================================================
# CLAUDE CONTEXT - SUBMIT RASTER INTERFACE MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Submit Raster Job
# PURPOSE: HTMX interface for ProcessRasterV2Job submission
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: SubmitRasterInterface
# DEPENDENCIES: azure.functions, web_interfaces.base
# ============================================================================
"""
Submit Raster interface module.

Exports the SubmitRasterInterface class for registration.
"""

from web_interfaces.submit_raster.interface import SubmitRasterInterface

__all__ = ['SubmitRasterInterface']
