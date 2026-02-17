# ============================================================================
# STAC RENDERS EXTENSION BUILDER
# ============================================================================
# EPOCH: 4 - ACTIVE (Aligned with Epoch 5 patterns)
# STATUS: Service - STAC Renders Extension v2.0.0 builder
# PURPOSE: Build visualization renders from band statistics for TiTiler
# CREATED: 16 FEB 2026
# ============================================================================
"""
STAC Renders Extension Builder.

Ported from Epoch 5 (rmhdagmaster/handlers/raster/statistics.py).
Pure functions — no IO, no external dependencies beyond typing.

Builds STAC Renders Extension v2.0.0 objects from band statistics.
TiTiler reads these natively via /stac/tilejson.json?render_id=default.

Output goes into properties.renders on the STAC item.

Usage:
    from services.stac_renders import build_renders, recommend_rgb_bands

    renders = build_renders(
        raster_type="dem",
        band_count=1,
        dtype="float32",
        band_stats=[{"band": 1, "statistics": {"minimum": 0, "maximum": 8848}}],
    )
    # {"default": {"title": "Default visualization", "assets": ["data"],
    #              "rescale": [[0, 9732]], "colormap_name": "terrain"},
    #  "grayscale": {"title": "Grayscale", "assets": ["data"],
    #                "rescale": [[0, 9732]]}}
"""

from typing import Any, Dict, List, Optional


# ============================================================================
# COLORMAP LOOKUP
# ============================================================================

COLORMAPS = {
    "dem": "terrain",
    "categorical": "tab20",
    "flood_depth": "blues",
    "flood_probability": "reds",
    "vegetation_index": "rdylgn",
    "population": "ylorrd",
    "continuous": "viridis",
}


# ============================================================================
# RENDERS BUILDER
# ============================================================================

def build_renders(
    raster_type: str,
    band_count: int,
    dtype: str,
    band_stats: Optional[List[Dict]],
    rgb_bands: Optional[List[int]] = None,
) -> Optional[Dict]:
    """
    Build STAC Renders Extension object from band statistics.

    The renders dict goes into properties.renders on the STAC item.
    TiTiler reads this natively via /stac/tilejson.json?render_id=default.

    Args:
        raster_type: Detected raster type (rgb, rgba, dem, multispectral, etc.)
        band_count: Number of bands
        dtype: Data type string (uint8, float32, etc.)
        band_stats: Per-band statistics from rasterio extraction
        rgb_bands: Recommended RGB band indexes (1-based), or auto-detected

    Returns:
        Renders dict or None if no renders could be built
    """
    if not band_stats:
        return None

    renders: Dict[str, Any] = {}

    if raster_type in ("rgb", "rgba"):
        # RGB/RGBA: no colormap, RGBA excludes alpha band
        render: Dict[str, Any] = {"title": "Natural color", "assets": ["data"]}
        if raster_type == "rgba":
            render["bidx"] = [1, 2, 3]  # exclude alpha band
        if dtype != "uint8" and band_stats:
            # Non-uint8 RGB needs rescale per band
            rescale_list = [
                [0, int(bs["statistics"]["maximum"] * 1.1)]
                for bs in band_stats[:3]
                if bs.get("statistics")
            ]
            if rescale_list:
                render["rescale"] = rescale_list
        renders["default"] = render

    elif band_count == 1:
        # Single-band: rescale + colormap
        rescale = _get_single_band_rescale(band_stats, raster_type)
        colormap = recommend_colormap(raster_type)

        render = {"title": "Default visualization", "assets": ["data"]}
        if rescale:
            render["rescale"] = [rescale]
        if colormap:
            render["colormap_name"] = colormap
        renders["default"] = render

        # Add grayscale variant (no colormap)
        if rescale:
            renders["grayscale"] = {
                "title": "Grayscale",
                "assets": ["data"],
                "rescale": [rescale],
            }

    elif raster_type == "multispectral":
        # Multi-band: select natural color bands
        bidx = rgb_bands or recommend_rgb_bands(band_count)
        if not bidx:
            return None

        render = {
            "title": "Natural color",
            "assets": ["data"],
            "bidx": bidx,
        }
        if dtype != "uint8" and band_stats:
            rescale_list = [
                [0, int(band_stats[b - 1]["statistics"]["maximum"] * 1.1)]
                for b in bidx
                if b <= len(band_stats) and band_stats[b - 1].get("statistics")
            ]
            if rescale_list:
                render["rescale"] = rescale_list
        renders["default"] = render

    return renders if renders else None


# ============================================================================
# RESCALE HELPERS
# ============================================================================

def _get_single_band_rescale(
    band_stats: Optional[List[Dict]],
    raster_type: str,
) -> Optional[List]:
    """
    Calculate rescale range for single-band rasters.

    Args:
        band_stats: Per-band statistics list
        raster_type: Detected raster type

    Returns:
        [min, max] rescale list or None if no stats available
    """
    if not band_stats or not band_stats[0].get("statistics"):
        return None

    stats = band_stats[0]["statistics"]
    min_val = stats["minimum"]
    max_val = stats["maximum"]

    if raster_type == "dem":
        # DEM: use actual minimum, 10% headroom on max
        return [int(min_val), int(max_val * 1.1)]

    # Other types: floor at 0, 10% headroom on max
    return [0, int(max_val * 1.1)]


# ============================================================================
# COLORMAP RECOMMENDATION
# ============================================================================

def recommend_colormap(raster_type: str) -> Optional[str]:
    """
    Recommend a colormap for the given raster type.

    RGB, RGBA, and multispectral types don't use colormaps.
    Unknown types default to viridis.

    Args:
        raster_type: Detected raster type

    Returns:
        Colormap name or None for RGB/RGBA/multispectral
    """
    if raster_type in ("rgb", "rgba", "multispectral"):
        return None
    return COLORMAPS.get(raster_type, "viridis")


# ============================================================================
# RGB BAND RECOMMENDATION
# ============================================================================

def recommend_rgb_bands(band_count: int) -> Optional[List[int]]:
    """
    Recommend RGB band indexes for natural color display.

    Based on common satellite sensor band configurations:
    - 7-9 bands: WorldView (natural color = bands 5, 3, 2)
    - 10-13 bands: Sentinel/Landsat (natural color = bands 4, 3, 2)
    - 4+ bands: Default to first 3 bands

    Args:
        band_count: Total number of bands

    Returns:
        List of 3 band indexes (1-based) or None if band_count < 4
    """
    if band_count in (7, 8, 9):
        return [5, 3, 2]  # WorldView natural color
    if band_count in (10, 11, 12, 13):
        return [4, 3, 2]  # Sentinel/Landsat
    if band_count >= 4:
        return [1, 2, 3]  # Default first 3
    return None


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'build_renders',
    'recommend_colormap',
    'recommend_rgb_bands',
    'COLORMAPS',
]
