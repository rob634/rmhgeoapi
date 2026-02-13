# ============================================================================
# CLAUDE CONTEXT - FATHOM VRT MERGE UTILITY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Utility - VRT-based spatial merge for FATHOM tiles
# PURPOSE: Memory-efficient tile merging using GDAL VRT streaming
# LAST_REVIEWED: 24 JAN 2026
# EXPORTS: merge_tiles_vrt
# DEPENDENCIES: osgeo.gdal
# ============================================================================
"""
FATHOM VRT Merge Utility.

Provides memory-efficient spatial merging of FATHOM tiles using GDAL's
Virtual Raster (VRT) format. This approach streams data through disk
instead of loading all tiles into RAM.

Memory Usage:
    - Traditional rasterio.merge: ~2-5GB peak for 16 tiles
    - VRT approach: ~500MB constant (streaming)

How it works:
    1. Create VRT for each band (tiny XML file, no data loaded)
    2. Stack VRTs into multi-band VRT
    3. gdal.Translate to COG (streams through CPL_TMPDIR)
    4. GDAL uses Azure Files mount for temp files

Requirements:
    - GDAL/osgeo installed
    - CPL_TMPDIR set to writable directory (ideally Azure Files mount)
"""

import os
import uuid
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "fathom_vrt_merge"
)


def merge_tiles_vrt(
    tile_paths: List[str],
    output_path: str,
    band_names: List[str],
    mount_path: Optional[str] = None,
    compress: str = "DEFLATE",
    predictor: int = 2,
    blocksize: int = 512
) -> Dict[str, Any]:
    """
    Merge tiles using GDAL VRT - streams data through disk.

    This is the memory-efficient alternative to rasterio.merge().
    Instead of loading all tile data into RAM, it creates a virtual
    raster that references the tiles and streams the output.

    Args:
        tile_paths: List of paths to input tile GeoTIFFs
        output_path: Path for output COG
        band_names: List of band names (e.g., ["RP5", "RP10", ...])
        mount_path: Path for temporary VRT files (defaults to system temp)
        compress: Compression method (DEFLATE, LZW, ZSTD)
        predictor: Compression predictor (2 for horizontal differencing)
        blocksize: Tile block size in pixels

    Returns:
        dict with:
            - success: True if merge completed
            - output_path: Path to output COG
            - bounds: Bounding box dict {west, south, east, north}
            - width: Output raster width in pixels
            - height: Output raster height in pixels
            - error: Error message if failed

    Example:
        result = merge_tiles_vrt(
            tile_paths=["/tmp/tile1.tif", "/tmp/tile2.tif"],
            output_path="/tmp/merged.tif",
            band_names=["RP5", "RP10", "RP20", "RP50", "RP75", "RP100", "RP250", "RP500"],
            mount_path="/mounts/etl-temp"
        )
    """
    try:
        from osgeo import gdal

        # Enable GDAL exceptions for better error handling
        gdal.UseExceptions()

        if not tile_paths:
            return {'success': False, 'error': 'No tile paths provided'}

        # Create temp directory for VRT files
        temp_base = mount_path or os.environ.get('CPL_TMPDIR') or '/tmp'
        temp_dir = Path(temp_base) / "fathom_vrt" / str(uuid.uuid4())[:8]
        temp_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"VRT merge: {len(tile_paths)} tiles → {output_path}")
        logger.debug(f"   Temp directory: {temp_dir}")

        try:
            # ═══════════════════════════════════════════════════════════════
            # STEP 1: Determine number of bands from first tile
            # ═══════════════════════════════════════════════════════════════
            first_ds = gdal.Open(tile_paths[0])
            if first_ds is None:
                return {'success': False, 'error': f'Could not open: {tile_paths[0]}'}

            num_bands = first_ds.RasterCount
            first_ds = None

            logger.debug(f"   Detected {num_bands} bands in source tiles")

            # ═══════════════════════════════════════════════════════════════
            # STEP 2: Create per-band VRTs (headers only - no data loaded)
            # ═══════════════════════════════════════════════════════════════
            band_vrts = []

            for band_idx in range(num_bands):
                band_num = band_idx + 1  # GDAL bands are 1-indexed
                vrt_path = str(temp_dir / f"band_{band_idx}.vrt")

                # BuildVRT reads headers only - minimal memory
                vrt_options = gdal.BuildVRTOptions(
                    bandList=[band_num],
                    resolution="highest",
                    resampleAlg="nearest",
                    srcNodata=-32768,
                    VRTNodata=-32768
                )

                vrt_ds = gdal.BuildVRT(vrt_path, tile_paths, options=vrt_options)

                if vrt_ds is None:
                    return {
                        'success': False,
                        'error': f'Failed to create VRT for band {band_num}'
                    }

                vrt_ds = None  # Close to flush
                band_vrts.append(vrt_path)

            logger.debug(f"   Created {len(band_vrts)} band VRTs")

            # ═══════════════════════════════════════════════════════════════
            # STEP 3: Stack into multi-band VRT
            # ═══════════════════════════════════════════════════════════════
            stacked_vrt = str(temp_dir / "stacked.vrt")

            stack_options = gdal.BuildVRTOptions(
                separate=True  # Stack bands instead of mosaic
            )

            stacked_ds = gdal.BuildVRT(stacked_vrt, band_vrts, options=stack_options)

            if stacked_ds is None:
                return {'success': False, 'error': 'Failed to create stacked VRT'}

            stacked_ds = None  # Close to flush

            logger.debug(f"   Created stacked VRT")

            # ═══════════════════════════════════════════════════════════════
            # STEP 4: Convert to COG (streaming through disk)
            # ═══════════════════════════════════════════════════════════════
            creation_options = [
                f"COMPRESS={compress}",
                f"PREDICTOR={predictor}",
                f"BLOCKSIZE={blocksize}",
                "BIGTIFF=IF_SAFER",
                "TILED=YES"
            ]

            translate_options = gdal.TranslateOptions(
                format="COG",
                creationOptions=creation_options
            )

            logger.debug(f"   Translating to COG...")

            result_ds = gdal.Translate(
                output_path,
                stacked_vrt,
                options=translate_options
            )

            if result_ds is None:
                return {'success': False, 'error': 'GDAL Translate failed'}

            # ═══════════════════════════════════════════════════════════════
            # STEP 5: Extract metadata from result
            # ═══════════════════════════════════════════════════════════════
            gt = result_ds.GetGeoTransform()
            width = result_ds.RasterXSize
            height = result_ds.RasterYSize

            # Calculate bounds from geotransform
            # gt = (x_origin, x_pixel_size, x_rotation, y_origin, y_rotation, y_pixel_size)
            bounds = {
                'west': gt[0],
                'east': gt[0] + width * gt[1],
                'north': gt[3],
                'south': gt[3] + height * gt[5]
            }

            # Set band descriptions if provided
            if band_names:
                for i, name in enumerate(band_names[:result_ds.RasterCount]):
                    band = result_ds.GetRasterBand(i + 1)
                    band.SetDescription(name)

            result_ds = None  # Close and flush

            logger.debug(f"   COG created: {width}x{height} pixels")
            logger.debug(f"   Bounds: {bounds}")

            return {
                'success': True,
                'output_path': output_path,
                'bounds': bounds,
                'width': width,
                'height': height,
                'band_count': num_bands
            }

        finally:
            # Cleanup temp VRTs
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as cleanup_error:
                logger.warning(f"   ⚠️ Cleanup failed: {cleanup_error}")

    except ImportError:
        return {
            'success': False,
            'error': 'GDAL not available - install osgeo/gdal'
        }

    except Exception as e:
        logger.error(f"VRT merge failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'success': False,
            'error': str(e)
        }


def merge_tiles_vrt_multiband(
    tile_paths: List[str],
    output_path: str,
    band_indices: Optional[List[int]] = None,
    mount_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Merge multi-band tiles preserving all bands.

    Alternative to merge_tiles_vrt when you want to keep all bands
    in a single operation without per-band VRT creation.

    Args:
        tile_paths: List of paths to input tile GeoTIFFs
        output_path: Path for output COG
        band_indices: Optional list of band indices to include (1-indexed)
        mount_path: Path for temporary files

    Returns:
        dict with success status and metadata
    """
    try:
        from osgeo import gdal
        gdal.UseExceptions()

        if not tile_paths:
            return {'success': False, 'error': 'No tile paths provided'}

        temp_base = mount_path or os.environ.get('CPL_TMPDIR') or '/tmp'
        temp_dir = Path(temp_base) / "fathom_vrt" / str(uuid.uuid4())[:8]
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Create single VRT from all tiles (all bands)
            vrt_path = str(temp_dir / "merged.vrt")

            vrt_options_kwargs = {
                'resolution': 'highest',
                'resampleAlg': 'nearest',
                'srcNodata': -32768,
                'VRTNodata': -32768
            }

            if band_indices:
                vrt_options_kwargs['bandList'] = band_indices

            vrt_options = gdal.BuildVRTOptions(**vrt_options_kwargs)
            vrt_ds = gdal.BuildVRT(vrt_path, tile_paths, options=vrt_options)

            if vrt_ds is None:
                return {'success': False, 'error': 'Failed to create VRT'}

            vrt_ds = None

            # Convert to COG
            translate_options = gdal.TranslateOptions(
                format="COG",
                creationOptions=[
                    "COMPRESS=DEFLATE",
                    "PREDICTOR=2",
                    "BLOCKSIZE=512",
                    "BIGTIFF=IF_SAFER"
                ]
            )

            result_ds = gdal.Translate(output_path, vrt_path, options=translate_options)

            if result_ds is None:
                return {'success': False, 'error': 'GDAL Translate failed'}

            gt = result_ds.GetGeoTransform()
            width = result_ds.RasterXSize
            height = result_ds.RasterYSize
            band_count = result_ds.RasterCount

            bounds = {
                'west': gt[0],
                'east': gt[0] + width * gt[1],
                'north': gt[3],
                'south': gt[3] + height * gt[5]
            }

            result_ds = None

            return {
                'success': True,
                'output_path': output_path,
                'bounds': bounds,
                'width': width,
                'height': height,
                'band_count': band_count
            }

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    except Exception as e:
        return {'success': False, 'error': str(e)}


# Export functions
__all__ = ['merge_tiles_vrt', 'merge_tiles_vrt_multiband']
