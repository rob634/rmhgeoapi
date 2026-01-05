# ============================================================================
# XARRAY API CONFIGURATION
# ============================================================================
# STATUS: API module config - Environment-based settings for xarray operations
# PURPOSE: Configuration for xarray direct access API with named locations
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: XarrayAPIConfig, get_xarray_api_config
# DEPENDENCIES: Standard library only
# ============================================================================
"""
xarray API Configuration.

Configuration for the xarray direct access API.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class XarrayAPIConfig:
    """Configuration for xarray API endpoints."""

    # Azure storage account for Zarr access
    storage_account: str = "rmhazuregeo"

    # Default aggregation method
    default_aggregation: str = "mean"

    # Default temporal resolution
    default_temporal_resolution: str = "monthly"

    # Maximum time range (days) to prevent huge queries
    max_time_range_days: int = 3650  # 10 years

    # Default output format for aggregation
    default_format: str = "json"

    # Default colormap for image output
    default_colormap: str = "viridis"

    # Named locations for point queries (same as raster API)
    named_locations: dict = None

    def __post_init__(self):
        if self.named_locations is None:
            self.named_locations = {
                "washington_dc": (-77.0369, 38.9072),
                "new_york": (-74.006, 40.7128),
                "los_angeles": (-118.2437, 34.0522),
                "chicago": (-87.6298, 41.8781),
                "houston": (-95.3698, 29.7604),
                "phoenix": (-112.0740, 33.4484),
                "philadelphia": (-75.1652, 39.9526),
                "san_antonio": (-98.4936, 29.4241),
                "san_diego": (-117.1611, 32.7157),
                "dallas": (-96.7970, 32.7767),
                "london": (-0.1276, 51.5074),
                "paris": (2.3522, 48.8566),
                "tokyo": (139.6917, 35.6895),
                "sydney": (151.2093, -33.8688),
            }


_config: Optional[XarrayAPIConfig] = None


def get_xarray_api_config() -> XarrayAPIConfig:
    """Get or create xarray API configuration singleton."""
    global _config
    if _config is None:
        _config = XarrayAPIConfig(
            storage_account=os.getenv("AZURE_STORAGE_ACCOUNT", "rmhazuregeo"),
            default_aggregation=os.getenv("XARRAY_API_DEFAULT_AGG", "mean"),
            default_temporal_resolution=os.getenv("XARRAY_API_TEMPORAL_RES", "monthly"),
            max_time_range_days=int(os.getenv("XARRAY_API_MAX_DAYS", "3650")),
        )
    return _config
