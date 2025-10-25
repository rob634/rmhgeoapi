# ============================================================================
# CLAUDE CONTEXT - STAC ITEM CREATION SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Create STAC Items with raster statistics
# PURPOSE: Package COG mosaics with metadata for web serving
# LAST_REVIEWED: 23 OCT 2025
# EXPORTS: create_stac_item, add_titiler_asset, calculate_bounds_from_tiles
# INTERFACES: None (standalone service)
# PYDANTIC_MODELS: None (returns STAC-compliant dict)
# DEPENDENCIES: rasterio (for bounds calculation)
# SOURCE: Statistics from service_statistics.py, job metadata
# SCOPE: Job-specific (runs during Stage 4 completion)
# VALIDATION: STAC 1.0.0 specification compliance
# PATTERNS: Service layer, STAC best practices
# ENTRY_POINTS: Called by controller_stage_raster.py during Stage 4
# INDEX:
#   - create_stac_item: Line 45
#   - add_titiler_asset: Line 165
#   - calculate_bounds_from_tiles: Line 220
# ============================================================================

"""
STAC Item Creation Service

Creates STAC (SpatioTemporal Asset Catalog) Items with raster statistics
for COG mosaics. This enables clients to discover optimal rendering parameters
without runtime computation.

STAC Extensions Used:
- raster: https://github.com/stac-extensions/raster (band statistics)

Author: Robert and Geospatial Claude Legion
Date: 23 OCT 2025
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import rasterio
import logging

logger = logging.getLogger(__name__)


def create_stac_item(
    job_id: str,
    mosaic_url: str,
    statistics: Dict[int, Dict[str, float]],
    bounds: List[float],
    crs: str = "EPSG:4326",
    band_names: Optional[List[str]] = None,
    band_descriptions: Optional[List[str]] = None,
    datetime_acquired: Optional[datetime] = None
) -> dict:
    """
    Create a STAC Item with raster statistics.

    Args:
        job_id: Unique job identifier (becomes STAC Item ID)
        mosaic_url: URL to MosaicJSON file
        statistics: Dict from calculate_mosaic_statistics():
            {1: {'minimum': 1, 'maximum': 255, ...}, ...}
        bounds: Geographic bounds [west, south, east, north] in EPSG:4326
        crs: Coordinate reference system (default: EPSG:4326)
        band_names: Names for bands (default: Red, Green, Blue)
        band_descriptions: Descriptions for bands (optional)
        datetime_acquired: When imagery was acquired (default: now)

    Returns:
        STAC Item dict ready to serialize to JSON

    Example:
        >>> stats = calculate_mosaic_statistics(tiles)
        >>> stac = create_stac_item(
        ...     job_id='antigua_50cm',
        ...     mosaic_url='https://storage/mosaic.json',
        ...     statistics=stats,
        ...     bounds=[-61.944, 16.976, -61.611, 17.212]
        ... )
        >>> import json
        >>> with open('stac.json', 'w') as f:
        ...     json.dump(stac, f, indent=2)

    References:
        - STAC Spec: https://stacspec.org/
        - Raster Extension: https://github.com/stac-extensions/raster
    """
    # Default band names for RGB imagery
    if band_names is None:
        num_bands = len(statistics)
        if num_bands == 3:
            band_names = ['Red', 'Green', 'Blue']
        elif num_bands == 4:
            band_names = ['Red', 'Green', 'Blue', 'NIR']
        else:
            band_names = [f'Band {i}' for i in range(1, num_bands + 1)]

    # Default acquisition time to now
    if datetime_acquired is None:
        datetime_acquired = datetime.now(timezone.utc)

    # Convert statistics to STAC raster:bands format
    raster_bands = []

    for band_idx, band_name in enumerate(band_names, start=1):
        if band_idx in statistics:
            band_stats = statistics[band_idx]

            band_def = {
                "name": band_name,
                "data_type": "uint8",  # Adjust based on your data
                "statistics": {
                    "minimum": band_stats['minimum'],
                    "maximum": band_stats['maximum'],
                    "mean": round(band_stats['mean'], 2),
                    "stddev": round(band_stats['stddev'], 2)
                }
            }

            # Add description if provided
            if band_descriptions and band_idx <= len(band_descriptions):
                band_def['description'] = band_descriptions[band_idx - 1]

            raster_bands.append(band_def)

    # Calculate geometry from bounds
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [bounds[0], bounds[1]],  # Southwest
            [bounds[2], bounds[1]],  # Southeast
            [bounds[2], bounds[3]],  # Northeast
            [bounds[0], bounds[3]],  # Northwest
            [bounds[0], bounds[1]]   # Close polygon
        ]]
    }

    # Create STAC Item
    stac_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
        ],
        "id": job_id,
        "geometry": geometry,
        "bbox": bounds,
        "properties": {
            "datetime": datetime_acquired.isoformat(),
            "title": f"COG Mosaic - {job_id}",
            "description": f"Cloud-Optimized GeoTIFF mosaic with {len(raster_bands)} bands",
            "proj:epsg": int(crs.split(':')[1]) if ':' in crs else None
        },
        "assets": {
            "cog_mosaic": {
                "href": mosaic_url,
                "type": "application/json",
                "roles": ["data"],
                "title": "MosaicJSON Index"
            }
        },
        "summaries": {
            "raster:bands": raster_bands
        }
    }

    logger.info(f"✅ Created STAC Item for {job_id}")
    logger.info(f"  Bounds: {bounds}")
    logger.info(f"  Bands: {len(raster_bands)}")
    logger.info(f"  CRS: {crs}")
    logger.info(f"  Statistics available for consistent rendering")

    return stac_item


def add_titiler_asset(
    stac_item: dict,
    titiler_endpoint: str,
    mosaic_id: str,
    band_index: int = 0
) -> dict:
    """
    Add TiTiler tile serving endpoint to STAC Item.

    This creates a ready-to-use tile URL with pre-configured rescale values
    from the raster statistics.

    Args:
        stac_item: STAC Item dict
        titiler_endpoint: Base TiTiler URL (e.g., https://titiler.io)
        mosaic_id: MosaicJSON identifier in TiTiler
        band_index: Which band's statistics to use (default: 0 = Red)

    Returns:
        Updated STAC Item with 'visual' asset

    Example:
        >>> stac = create_stac_item(...)
        >>> stac = add_titiler_asset(
        ...     stac,
        ...     titiler_endpoint='https://titiler.io',
        ...     mosaic_id='antigua_50cm'
        ... )
        >>> print(stac['assets']['visual']['href'])
        https://titiler.io/mosaics/antigua_50cm/tiles/{z}/{x}/{y}.png?rescale=1,255
    """
    raster_bands = stac_item.get('summaries', {}).get('raster:bands', [])

    if raster_bands and band_index < len(raster_bands):
        # Use specified band's statistics
        band_stats = raster_bands[band_index]['statistics']
        min_val = band_stats['minimum']
        max_val = band_stats['maximum']

        # Create tile URL template with rescale parameter
        tile_url = (
            f"{titiler_endpoint}/mosaics/{mosaic_id}/tiles/"
            f"{{z}}/{{x}}/{{y}}.png?"
            f"rescale={min_val},{max_val}"
        )

        stac_item['assets']['visual'] = {
            "href": tile_url,
            "type": "image/png",
            "roles": ["visual"],
            "title": "RGB Visual Tiles",
            "description": f"Pre-configured stretch: {min_val}-{max_val}"
        }

        logger.info(f"✅ Added TiTiler visual asset")
        logger.info(f"  URL: {tile_url}")
        logger.info(f"  Rescale: {min_val},{max_val}")

    else:
        logger.warning(f"Cannot add TiTiler asset: band {band_index} not found")

    return stac_item


def calculate_bounds_from_tiles(
    cog_tiles: List[str],
    target_crs: str = "EPSG:4326"
) -> List[float]:
    """
    Calculate geographic bounds from COG tiles.

    Args:
        cog_tiles: List of COG file paths or URLs
        target_crs: CRS for output bounds (default: EPSG:4326)

    Returns:
        Bounds as [west, south, east, north] in target CRS

    Example:
        >>> tiles = ['tile_0_0_cog.tif', 'tile_0_1_cog.tif']
        >>> bounds = calculate_bounds_from_tiles(tiles)
        >>> print(bounds)
        [-61.944, 16.976, -61.611, 17.212]
    """
    logger.info(f"Calculating bounds from {len(cog_tiles)} tiles...")

    min_west = float('inf')
    min_south = float('inf')
    max_east = float('-inf')
    max_north = float('-inf')

    tiles_read = 0

    for tile_path in cog_tiles:
        try:
            with rasterio.open(tile_path) as src:
                # Get bounds in tile's native CRS
                tile_bounds = src.bounds

                # If tile CRS matches target, use directly
                if src.crs.to_string() == target_crs:
                    west, south, east, north = tile_bounds
                else:
                    # Transform bounds to target CRS
                    from rasterio.warp import transform_bounds
                    west, south, east, north = transform_bounds(
                        src.crs,
                        target_crs,
                        *tile_bounds
                    )

                # Update global bounds
                min_west = min(min_west, west)
                min_south = min(min_south, south)
                max_east = max(max_east, east)
                max_north = max(max_north, north)

                tiles_read += 1

        except Exception as e:
            logger.warning(f"Failed to read bounds from {tile_path}: {e}")
            continue

    bounds = [min_west, min_south, max_east, max_north]

    logger.info(f"✅ Bounds calculated from {tiles_read} tiles")
    logger.info(f"  West: {min_west:.6f}")
    logger.info(f"  South: {min_south:.6f}")
    logger.info(f"  East: {max_east:.6f}")
    logger.info(f"  North: {max_north:.6f}")

    return bounds
