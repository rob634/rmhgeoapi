# ============================================================================
# STAC API CONFIGURATION
# ============================================================================
# STATUS: Trigger layer config - STAC catalog metadata and base URL settings
# PURPOSE: Configuration for STAC catalog metadata and base URL settings
# CREATED: 24 JAN 2026 (Moved from stac_api/config.py)
# EXPORTS: STACAPIConfig, get_stac_config
# DEPENDENCIES: pydantic
# ============================================================================
"""
STAC API Configuration.

Minimal configuration for STAC API module.
Auto-detects base URL from requests if not explicitly set.
"""

from typing import Optional
from pydantic import BaseModel, Field


class STACAPIConfig(BaseModel):
    """STAC API module configuration."""

    catalog_id: str = Field(
        default="rmh-geospatial-stac",
        description="STAC catalog ID"
    )

    catalog_title: str = Field(
        default="RMH Geospatial STAC API",
        description="Human-readable catalog title"
    )

    catalog_description: str = Field(
        default="STAC catalog for geospatial raster and vector data with OAuth-based tile serving via TiTiler-pgSTAC",
        description="Catalog description"
    )

    stac_version: str = Field(
        default="1.0.0",
        description="STAC specification version"
    )

    stac_base_url: Optional[str] = Field(
        default=None,
        description="Base URL for STAC API (auto-detected if None)"
    )


def get_stac_config() -> STACAPIConfig:
    """Get STAC API configuration (singleton pattern)."""
    return STACAPIConfig()
