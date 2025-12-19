"""
xarray API Output Helpers.

Functions for converting xarray results to output formats:
- GeoTIFF creation with proper georeferencing
- PNG rendering with colormaps
"""

import io
import logging
from typing import Tuple, Optional
import numpy as np

logger = logging.getLogger(__name__)


# Colormap definitions (matplotlib-style but without matplotlib dependency)
COLORMAPS = {
    "viridis": [
        (68, 1, 84), (72, 35, 116), (64, 67, 135), (52, 94, 141),
        (41, 120, 142), (32, 144, 140), (34, 167, 132), (68, 190, 112),
        (121, 209, 81), (189, 222, 38), (253, 231, 37)
    ],
    "turbo": [
        (48, 18, 59), (86, 36, 163), (107, 62, 196), (116, 95, 217),
        (111, 131, 230), (95, 166, 236), (71, 196, 235), (52, 218, 222),
        (56, 234, 194), (82, 245, 161), (125, 251, 125), (175, 252, 89),
        (218, 247, 57), (250, 231, 36), (254, 204, 36), (248, 170, 44),
        (236, 133, 52), (218, 95, 57), (194, 60, 59), (166, 33, 55),
        (136, 13, 47), (103, 3, 37)
    ],
    "plasma": [
        (13, 8, 135), (75, 3, 161), (125, 3, 168), (168, 34, 150),
        (203, 70, 121), (229, 107, 93), (248, 148, 65), (253, 195, 40),
        (240, 249, 33)
    ],
    "inferno": [
        (0, 0, 4), (40, 11, 84), (101, 21, 110), (159, 42, 99),
        (212, 72, 66), (245, 125, 21), (250, 193, 39), (252, 255, 164)
    ],
    "coolwarm": [
        (59, 76, 192), (98, 130, 234), (141, 176, 254), (184, 208, 249),
        (221, 221, 221), (245, 196, 173), (244, 154, 123), (222, 96, 77),
        (180, 4, 38)
    ],
    "RdYlBu": [
        (165, 0, 38), (215, 48, 39), (244, 109, 67), (253, 174, 97),
        (254, 224, 144), (255, 255, 191), (224, 243, 248), (171, 217, 233),
        (116, 173, 209), (69, 117, 180), (49, 54, 149)
    ]
}


def _interpolate_colormap(colormap_name: str, n_colors: int = 256) -> np.ndarray:
    """
    Interpolate colormap to n_colors.

    Args:
        colormap_name: Name of colormap
        n_colors: Number of output colors

    Returns:
        Array of shape (n_colors, 3) with RGB values
    """
    colors = COLORMAPS.get(colormap_name, COLORMAPS["viridis"])
    colors = np.array(colors, dtype=np.float32)

    # Interpolate to n_colors
    x_old = np.linspace(0, 1, len(colors))
    x_new = np.linspace(0, 1, n_colors)

    result = np.zeros((n_colors, 3), dtype=np.uint8)
    for i in range(3):
        result[:, i] = np.interp(x_new, x_old, colors[:, i]).astype(np.uint8)

    return result


def render_png(
    data: np.ndarray,
    colormap: str = "viridis",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None
) -> bytes:
    """
    Render numpy array as PNG image with colormap.

    Args:
        data: 2D numpy array
        colormap: Colormap name
        vmin: Minimum value for scaling (default: data min)
        vmax: Maximum value for scaling (default: data max)

    Returns:
        PNG image as bytes
    """
    from PIL import Image

    # Handle NaN values
    mask = np.isnan(data)
    data_clean = np.where(mask, 0, data)

    # Normalize to 0-255
    if vmin is None:
        vmin = float(np.nanmin(data))
    if vmax is None:
        vmax = float(np.nanmax(data))

    if vmax == vmin:
        normalized = np.zeros_like(data_clean, dtype=np.uint8)
    else:
        normalized = ((data_clean - vmin) / (vmax - vmin) * 255).clip(0, 255).astype(np.uint8)

    # Apply colormap
    cmap = _interpolate_colormap(colormap, 256)
    rgb = cmap[normalized]

    # Set masked pixels to transparent/black
    if mask.any():
        rgb[mask] = [0, 0, 0]

    # Create PIL image
    img = Image.fromarray(rgb, mode='RGB')

    # Save to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


def create_geotiff(
    data: np.ndarray,
    bbox: Tuple[float, float, float, float],
    lat_coords: Optional[np.ndarray] = None,
    lon_coords: Optional[np.ndarray] = None,
    crs: str = "EPSG:4326"
) -> bytes:
    """
    Create GeoTIFF from numpy array with georeferencing.

    Args:
        data: 2D numpy array
        bbox: Bounding box (minx, miny, maxx, maxy)
        lat_coords: Latitude coordinates (optional, for precise georef)
        lon_coords: Longitude coordinates (optional, for precise georef)
        crs: Coordinate reference system

    Returns:
        GeoTIFF as bytes
    """
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.io import MemoryFile

    minx, miny, maxx, maxy = bbox
    height, width = data.shape

    # Create transform from bounds
    if lat_coords is not None and lon_coords is not None:
        # Use actual coordinates for more precise georeferencing
        # Assume regular grid
        x_res = (lon_coords[-1] - lon_coords[0]) / (len(lon_coords) - 1) if len(lon_coords) > 1 else 1
        y_res = (lat_coords[0] - lat_coords[-1]) / (len(lat_coords) - 1) if len(lat_coords) > 1 else 1

        # Upper-left corner
        transform = rasterio.transform.from_origin(
            float(lon_coords[0]) - x_res / 2,
            float(lat_coords[0]) + abs(y_res) / 2,
            abs(x_res),
            abs(y_res)
        )
    else:
        transform = from_bounds(minx, miny, maxx, maxy, width, height)

    # Handle NaN values
    nodata = -9999.0
    data_clean = np.where(np.isnan(data), nodata, data).astype(np.float32)

    # Create GeoTIFF in memory
    memfile = MemoryFile()
    with memfile.open(
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=data_clean.dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress='deflate'
    ) as dst:
        dst.write(data_clean, 1)

    return memfile.read()


def create_geotiff_rgb(
    data: np.ndarray,
    bbox: Tuple[float, float, float, float],
    colormap: str = "viridis",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None
) -> bytes:
    """
    Create RGB GeoTIFF with colormap applied.

    Args:
        data: 2D numpy array
        bbox: Bounding box (minx, miny, maxx, maxy)
        colormap: Colormap name
        vmin: Minimum value for scaling
        vmax: Maximum value for scaling

    Returns:
        RGB GeoTIFF as bytes
    """
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.io import MemoryFile

    minx, miny, maxx, maxy = bbox
    height, width = data.shape

    # Handle NaN values
    mask = np.isnan(data)
    data_clean = np.where(mask, 0, data)

    # Normalize
    if vmin is None:
        vmin = float(np.nanmin(data))
    if vmax is None:
        vmax = float(np.nanmax(data))

    if vmax == vmin:
        normalized = np.zeros_like(data_clean, dtype=np.uint8)
    else:
        normalized = ((data_clean - vmin) / (vmax - vmin) * 255).clip(0, 255).astype(np.uint8)

    # Apply colormap
    cmap = _interpolate_colormap(colormap, 256)
    rgb = cmap[normalized]  # Shape: (height, width, 3)

    # Transpose for rasterio (bands first)
    rgb_bands = np.transpose(rgb, (2, 0, 1))  # Shape: (3, height, width)

    transform = from_bounds(minx, miny, maxx, maxy, width, height)

    # Create GeoTIFF in memory
    memfile = MemoryFile()
    with memfile.open(
        driver='GTiff',
        height=height,
        width=width,
        count=3,
        dtype=np.uint8,
        crs="EPSG:4326",
        transform=transform,
        compress='deflate'
    ) as dst:
        dst.write(rgb_bands)

    return memfile.read()
