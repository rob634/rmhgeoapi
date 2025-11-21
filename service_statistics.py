# ============================================================================
# CLAUDE CONTEXT - GLOBAL STATISTICS SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Calculate global min/max/mean/stddev for COG mosaics
# PURPOSE: Pre-compute statistics for consistent TiTiler rendering
# LAST_REVIEWED: 23 OCT 2025
# EXPORTS: calculate_mosaic_statistics, calculate_percentile_statistics
# INTERFACES: None (standalone service)
# PYDANTIC_MODELS: None (returns plain dict)
# DEPENDENCIES: numpy, rasterio (GDAL)
# SOURCE: COG tiles from blob storage or local filesystem
# SCOPE: Job-specific (runs during Stage 4 completion)
# VALIDATION: Input validation via type hints and runtime checks
# PATTERNS: Service layer, single responsibility
# ENTRY_POINTS: Called by controller_stage_raster.py during Stage 4
# INDEX:
#   - calculate_mosaic_statistics: Line 50
#   - calculate_percentile_statistics: Line 180
# ============================================================================

"""
Global Statistics Service

Calculates global min/max/mean/stddev across COG tile mosaics for consistent
rendering. Uses COG internal overviews for fast sampling (same technique as
GDAL/QGIS when opening VRT files).

This solves the "VRT seamless rendering" problem for MosaicJSON:
- VRT: QGIS samples on-demand, caches in .qgs project file
- Our approach: Pre-compute in Stage 4, store in STAC metadata

"""

import numpy as np
import rasterio
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def calculate_mosaic_statistics(
    cog_tiles: List[str],
    overview_level: int = 2,
    nodata_value: Optional[int] = 0
) -> Dict[int, Dict[str, float]]:
    """
    Calculate global min/max/mean/stddev across all COG tiles.

    Uses COG internal overviews for speed (same technique as GDAL/QGIS).

    Args:
        cog_tiles: List of COG file paths or URLs
        overview_level: Which overview to read:
            - 0 = full resolution (slowest)
            - 1 = 1/2 resolution (4x faster)
            - 2 = 1/4 resolution (16x faster) ← DEFAULT
            - 3 = 1/8 resolution (64x faster)
        nodata_value: Value to exclude from statistics (None = include all)

    Returns:
        Dict mapping band number to statistics:
        {
            1: {'minimum': 1, 'maximum': 255, 'mean': 44.2, 'stddev': 42.1},
            2: {'minimum': 1, 'maximum': 255, 'mean': 51.3, 'stddev': 38.7},
            3: {'minimum': 1, 'maximum': 255, 'mean': 39.8, 'stddev': 45.2}
        }

    Example:
        >>> tiles = ['tile_0_0_cog.tif', 'tile_0_1_cog.tif', ...]
        >>> stats = calculate_mosaic_statistics(tiles, overview_level=2)
        >>> print(stats[1]['minimum'])  # Red band minimum
        1

    Performance:
        For 221 tiles @ 5000×5000 pixels:
        - Full resolution: ~5 billion pixels (~20 GB to read) → 5+ minutes
        - Overview level 2: ~300 million pixels (~1.2 GB) → 3 minutes
        - Overview level 3: ~75 million pixels (~300 MB) → 1 minute

    Notes:
        - Replicates what GDAL does when QGIS opens a VRT
        - GDAL automatically uses COG overviews when downsampling
        - Consistent with QGIS "Estimate (faster)" statistics mode
    """
    logger.info(f"Calculating global statistics across {len(cog_tiles)} tiles...")
    logger.info(f"Using overview level {overview_level} (1/{2**overview_level} resolution)")

    # Collect per-tile statistics for each band
    band_stats = {}
    tiles_processed = 0
    tiles_failed = 0

    for tile_path in cog_tiles:
        try:
            with rasterio.open(tile_path) as src:
                # Determine output shape based on overview level
                # overview_level 0 = full res
                # overview_level 1 = 1/2 res (divide by 2)
                # overview_level 2 = 1/4 res (divide by 4)
                downsample_factor = 2 ** overview_level
                out_height = src.height // downsample_factor
                out_width = src.width // downsample_factor

                # Read downsampled data (GDAL uses overviews automatically)
                data = src.read(
                    out_shape=(src.count, out_height, out_width)
                )

                # Calculate statistics per band
                for band_idx in range(src.count):
                    band_num = band_idx + 1  # Bands are 1-indexed
                    band_data = data[band_idx]

                    # Filter out nodata values
                    if nodata_value is not None:
                        valid = band_data[band_data != nodata_value]
                    else:
                        valid = band_data.flatten()

                    if len(valid) > 0:
                        # Initialize band stats list if needed
                        if band_num not in band_stats:
                            band_stats[band_num] = []

                        # Store tile-level statistics
                        band_stats[band_num].append({
                            'min': int(valid.min()),
                            'max': int(valid.max()),
                            'mean': float(valid.mean()),
                            'stddev': float(valid.std())
                        })

            tiles_processed += 1
            if tiles_processed % 10 == 0:
                logger.info(f"  Processed {tiles_processed}/{len(cog_tiles)} tiles...")

        except Exception as e:
            tiles_failed += 1
            logger.warning(f"  Failed to read {tile_path}: {e}")
            continue

    # Summary
    logger.info(f"  Successfully processed: {tiles_processed}/{len(cog_tiles)} tiles")
    if tiles_failed > 0:
        logger.warning(f"  Failed tiles: {tiles_failed}")

    # Aggregate across all tiles to get global statistics
    global_stats = {}

    for band_num, tile_stats in band_stats.items():
        if not tile_stats:
            logger.warning(f"No valid data for band {band_num}")
            continue

        global_stats[band_num] = {
            'minimum': min(s['min'] for s in tile_stats),
            'maximum': max(s['max'] for s in tile_stats),
            'mean': float(np.mean([s['mean'] for s in tile_stats])),
            'stddev': float(np.mean([s['stddev'] for s in tile_stats]))
        }

    logger.info(f"✅ Global statistics computed for {len(global_stats)} bands:")
    for band_num, stats in global_stats.items():
        logger.info(
            f"  Band {band_num}: "
            f"min={stats['minimum']}, max={stats['maximum']}, "
            f"mean={stats['mean']:.1f}, stddev={stats['stddev']:.1f}"
        )

    return global_stats


def calculate_percentile_statistics(
    cog_tiles: List[str],
    percentiles: List[float] = [2.0, 98.0],
    overview_level: int = 2,
    nodata_value: Optional[int] = 0,
    max_tiles_sample: int = 50
) -> Dict[int, Dict[str, float]]:
    """
    Calculate percentile-based statistics for better contrast.

    Percentiles clip outliers for improved visual appearance.

    WARNING: This is memory-intensive! Collects all pixel values from sampled tiles.

    Args:
        cog_tiles: List of COG file paths
        percentiles: List of percentiles to compute (default: [2, 98])
        overview_level: Which overview to read
        nodata_value: Value to exclude
        max_tiles_sample: Max number of tiles to sample (memory limit)

    Returns:
        Dict mapping band number to percentile statistics:
        {
            1: {
                'p2': 5,      # 2nd percentile
                'p98': 245,   # 98th percentile
                'mean': 44.2,
                'stddev': 42.1
            }
        }

    Example:
        >>> stats = calculate_percentile_statistics(tiles, percentiles=[2, 98])
        >>> print(f"Stretch from {stats[1]['p2']} to {stats[1]['p98']}")
        Stretch from 5 to 245

    Notes:
        - More robust to outliers than min/max
        - Commonly used in remote sensing: 2%-98% stretch
        - Memory usage: ~100 MB per 50 tiles @ overview level 2
    """
    logger.info(f"Calculating percentile statistics ({percentiles})...")
    logger.info(f"  Sampling {min(max_tiles_sample, len(cog_tiles))} of {len(cog_tiles)} tiles")

    # Collect all pixel values (memory-intensive!)
    band_pixels = {}
    sampled_tiles = cog_tiles[:max_tiles_sample]

    for tile_path in sampled_tiles:
        try:
            with rasterio.open(tile_path) as src:
                downsample_factor = 2 ** overview_level
                out_height = src.height // downsample_factor
                out_width = src.width // downsample_factor

                data = src.read(out_shape=(src.count, out_height, out_width))

                for band_idx in range(src.count):
                    band_num = band_idx + 1
                    band_data = data[band_idx]

                    if nodata_value is not None:
                        valid = band_data[band_data != nodata_value]
                    else:
                        valid = band_data.flatten()

                    if len(valid) > 0:
                        if band_num not in band_pixels:
                            band_pixels[band_num] = []
                        band_pixels[band_num].append(valid)

        except Exception as e:
            logger.warning(f"Failed to read {tile_path}: {e}")
            continue

    # Calculate percentiles
    percentile_stats = {}

    for band_num, pixel_arrays in band_pixels.items():
        all_pixels = np.concatenate(pixel_arrays)

        percentile_stats[band_num] = {
            f'p{int(p)}': float(np.percentile(all_pixels, p))
            for p in percentiles
        }
        percentile_stats[band_num]['mean'] = float(all_pixels.mean())
        percentile_stats[band_num]['stddev'] = float(all_pixels.std())

        logger.info(f"  Band {band_num}: {percentile_stats[band_num]}")

    logger.info(f"✅ Percentile statistics computed for {len(percentile_stats)} bands")

    return percentile_stats
