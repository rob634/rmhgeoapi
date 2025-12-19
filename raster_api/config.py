"""
Raster API Configuration.

Configuration for the raster convenience API.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class RasterAPIConfig:
    """Configuration for Raster API endpoints."""

    # Default output format
    default_format: str = "png"

    # Default preview size
    default_preview_size: int = 512

    # Default colormap for visualization
    default_colormap: str = "viridis"

    # Maximum bbox size (prevents huge extractions)
    max_bbox_area_degrees: float = 100.0  # ~100 sq degrees

    # Default asset key to use
    default_asset: str = "data"

    # Named locations for point queries
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


_config: Optional[RasterAPIConfig] = None


def get_raster_api_config() -> RasterAPIConfig:
    """Get or create raster API configuration singleton."""
    global _config
    if _config is None:
        _config = RasterAPIConfig(
            default_format=os.getenv("RASTER_API_DEFAULT_FORMAT", "png"),
            default_preview_size=int(os.getenv("RASTER_API_PREVIEW_SIZE", "512")),
            default_colormap=os.getenv("RASTER_API_COLORMAP", "viridis"),
        )
    return _config
