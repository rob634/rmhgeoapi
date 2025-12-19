# ============================================================================
# CLAUDE CONTEXT - ZARR INTERFACE MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web interface - Zarr/xarray point query demo
# PURPOSE: Interactive map for querying CMIP6 Zarr data via TiTiler-xarray
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: ZarrInterface
# DEPENDENCIES: web_interfaces.base, config
# ============================================================================

from web_interfaces.zarr.interface import ZarrInterface

__all__ = ['ZarrInterface']
