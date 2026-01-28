# ============================================================================
# TILING SCHEME GENERATION SERVICE
# ============================================================================
# STATUS: Service layer - Stage 1 of Big Raster ETL workflow
# PURPOSE: Generate GeoJSON tiling schemes for large rasters in EPSG:4326
# LAST_REVIEWED: 27 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# V0.8.2: Row/column tile naming (tile_r{row}_c{col}) for clarity
# EXPORTS: generate_tiling_scheme
# DEPENDENCIES: rasterio, shapely
# ============================================================================
"""
Tiling Scheme Generation Service.

Generates GeoJSON tiling schemes for large rasters (1-30 GB) in EPSG:4326 output space.
Stage 1 of Big Raster ETL workflow.

Architecture:
    - Tiles are defined in EPSG:4326 OUTPUT space (not source CRS)
    - This ensures perfect tile alignment after reprojection (no seams)
    - Rio-cogeo handles source pixel sampling automatically via WarpedVRT
    - 512-pixel overlap aligns with COG 512×512 internal block structure

Exports:
    generate_tiling_scheme: Main handler function for tiling scheme generation
"""

import json
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Pydantic for band_names validation
from core.models.band_mapping import BandNames
from pydantic import ValidationError

# Logging
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "TilingScheme")

# Lazy imports for Azure environment compatibility
def _lazy_imports():
    """Lazy import to avoid module-level import failures."""
    import rasterio
    from rasterio.warp import transform_bounds
    from shapely.geometry import box, mapping
    return rasterio, transform_bounds, box, mapping


def calculate_optimal_tile_size(
    band_count: int,
    bit_depth: int,
    target_tile_mb: int = 300,
    compression_ratio: float = 1.5
) -> Tuple[int, int]:
    """
    Calculate optimal tile size based on raster characteristics.

    Targets 250-500MB uncompressed tiles with perfect 512px COG alignment.
    Optimized for VSI/HTTP streaming - smaller tiles = faster network transfer.

    Args:
        band_count: Number of bands (3, 4, 8, etc.)
        bit_depth: Bits per pixel (8, 16, 32)
        target_tile_mb: Target compressed size in MB (default: 300 = ~450MB uncompressed)
        compression_ratio: Expected compression (default: 1.5x for LZW/DEFLATE)

    Returns:
        Tuple of (tile_size_pixels, overlap_pixels)
        - tile_size_pixels: Always multiple of 512 (e.g., 23040 = 45×512)
        - overlap_pixels: Always 512 (exactly 1 COG block)

    Examples:
        >>> calculate_optimal_tile_size(3, 16)   # RGB 16-bit (WorldView-2 RGB)
        (8192, 512)  # 16×512 blocks → ~384 MB

        >>> calculate_optimal_tile_size(8, 16)  # 8-band 16-bit (WorldView-2 full)
        (5120, 512)  # 10×512 blocks → ~400 MB

    Profile-based recommendations (VSI-optimized sizes):
        - WorldView-2 RGB (3 bands, 16-bit):   8,192px → ~384MB per tile
        - WorldView-2 Full (8 bands, 16-bit):  5,120px → ~400MB per tile
        - Drone RGB 8-bit (3 bands, 8-bit):   11,264px → ~360MB per tile
        - Target: 250-500 MB uncompressed for efficient HTTP/VSI streaming
    """
    import math

    # Bytes per pixel from bit depth
    if bit_depth <= 8:
        bytes_per_pixel = 1  # uint8
    elif bit_depth <= 16:
        bytes_per_pixel = 2  # uint16
    elif bit_depth <= 32:
        bytes_per_pixel = 4  # uint32/float32
    else:
        bytes_per_pixel = 8  # float64 (rare)

    # Target uncompressed size accounting for compression
    target_uncompressed_mb = target_tile_mb * compression_ratio
    target_uncompressed_bytes = target_uncompressed_mb * 1024 * 1024

    # Calculate pixels per tile: pixels = bytes / (bands * bytes_per_pixel)
    pixels_per_tile = target_uncompressed_bytes / (band_count * bytes_per_pixel)

    # Tile size (square tiles)
    tile_size = int(math.sqrt(pixels_per_tile))

    # Round to nearest 512 pixels for perfect COG alignment
    tile_size = round(tile_size / 512) * 512

    # Clamp to safe limits (also multiples of 512)
    # Min: 5120 = 10×512 (for very high band count), Max: 20480 = 40×512 (for VSI streaming)
    tile_size = max(5120, min(20480, tile_size))

    # Fixed 512px overlap (exactly 1 COG block)
    overlap = 512

    return tile_size, overlap


def calculate_target_resolution(
    src_crs: str,
    src_bounds: Tuple[float, float, float, float],
    src_width: int,
    src_height: int,
    target_crs: str = "EPSG:4326"
) -> Tuple[Tuple[float, float, float, float], int, int, Tuple[float, float]]:
    """
    Calculate target resolution and dimensions in EPSG:4326.

    Maintains similar pixel count as source to preserve resolution.

    Args:
        src_crs: Source CRS (e.g., "EPSG:3857")
        src_bounds: Source bounds (minx, miny, maxx, maxy)
        src_width: Source width in pixels
        src_height: Source height in pixels
        target_crs: Target CRS (default: EPSG:4326)

    Returns:
        Tuple of:
            - target_bounds: (minx, miny, maxx, maxy) in target CRS
            - target_width: Width in pixels (same as source)
            - target_height: Height in pixels (same as source)
            - degrees_per_pixel: (degrees_per_pixel_x, degrees_per_pixel_y)
    """
    rasterio, transform_bounds, box, mapping = _lazy_imports()

    # Reproject bounds to EPSG:4326
    target_bounds = transform_bounds(src_crs, target_crs, *src_bounds)

    # Calculate extent in degrees
    width_degrees = target_bounds[2] - target_bounds[0]
    height_degrees = target_bounds[3] - target_bounds[1]

    # Maintain similar pixel count as source (preserves resolution)
    target_width = src_width
    target_height = src_height

    # Calculate degrees per pixel
    degrees_per_pixel_x = width_degrees / target_width
    degrees_per_pixel_y = height_degrees / target_height

    return (
        target_bounds,
        target_width,
        target_height,
        (degrees_per_pixel_x, degrees_per_pixel_y)
    )


def calculate_tile_grid(
    width: int,
    height: int,
    tile_size: int = 5000,
    overlap: int = 512
) -> Dict[str, Any]:
    """
    Calculate optimal tile grid for output raster dimensions.

    Args:
        width: Target width in pixels (EPSG:4326 output space)
        height: Target height in pixels (EPSG:4326 output space)
        tile_size: Tile size in pixels (default: 5000)
        overlap: Overlap in pixels (default: 512, matches COG blocksize)

    Returns:
        Grid metadata dict with:
            - rows: Number of tile rows
            - cols: Number of tile columns
            - tile_size_pixels: Tile size in pixels
            - overlap_pixels: Overlap in pixels
            - effective_tile_size: Tile size minus overlap
            - total_tiles: Total number of tiles (rows × cols)
            - overlap_percentage: Overlap as percentage of tile size
            - cog_blocksize: COG internal block size (always 512)
    """
    # Calculate number of tiles needed (accounting for overlap)
    effective_tile_size = tile_size - overlap

    cols = (width + effective_tile_size - 1) // effective_tile_size
    rows = (height + effective_tile_size - 1) // effective_tile_size

    return {
        "rows": rows,
        "cols": cols,
        "tile_size_pixels": tile_size,
        "overlap_pixels": overlap,
        "effective_tile_size": effective_tile_size,
        "total_tiles": rows * cols,
        "overlap_percentage": round((overlap / tile_size) * 100, 2),
        "cog_blocksize": 512
    }


def generate_tile_windows(
    target_width: int,
    target_height: int,
    tile_size: int = 5000,
    overlap: int = 512
) -> List[Dict[str, Any]]:
    """
    Generate tile windows in output pixel space.

    CRITICAL: These are pixel windows in EPSG:4326 output space,
    not source CRS pixel windows.

    Args:
        target_width: Target width in pixels (EPSG:4326 output)
        target_height: Target height in pixels (EPSG:4326 output)
        tile_size: Tile size in pixels (default: 5000)
        overlap: Overlap in pixels (default: 512)

    Returns:
        List of tile definition dicts with:
            - id: Sequential tile ID (0, 1, 2, ...)
            - tile_id: Semantic tile ID (tile_r0_c0, tile_r0_c1, ...)
            - row: Row index
            - col: Column index
            - pixel_window: {col_off, row_off, width, height}
            - target_width_pixels: Tile width (may be smaller at edges)
            - target_height_pixels: Tile height (may be smaller at edges)
    """
    grid = calculate_tile_grid(target_width, target_height, tile_size, overlap)
    effective_tile_size = grid["effective_tile_size"]

    tiles = []
    tile_id = 0

    for row in range(grid["rows"]):
        for col in range(grid["cols"]):
            # Calculate window with overlap (in output pixel space)
            col_off = col * effective_tile_size
            row_off = row * effective_tile_size

            # Tile width/height (may be smaller at edges)
            tile_width = min(tile_size, target_width - col_off)
            tile_height = min(tile_size, target_height - row_off)

            # Create tile definition
            # V0.8.2: Row/column naming for clarity (27 JAN 2026)
            tile = {
                "id": tile_id,
                "tile_id": f"tile_r{row}_c{col}",
                "row": row,
                "col": col,
                "pixel_window": {
                    "col_off": col_off,
                    "row_off": row_off,
                    "width": tile_width,
                    "height": tile_height
                },
                "target_width_pixels": tile_width,
                "target_height_pixels": tile_height
            }

            tiles.append(tile)
            tile_id += 1

    return tiles


def calculate_tile_bounds_4326(
    pixel_window: Dict[str, int],
    target_bounds: Tuple[float, float, float, float],
    degrees_per_pixel: Tuple[float, float]
) -> Tuple[float, float, float, float]:
    """
    Calculate EPSG:4326 bounds for tile from pixel window.

    Args:
        pixel_window: Pixel window dict (col_off, row_off, width, height)
        target_bounds: Full raster bounds in EPSG:4326
        degrees_per_pixel: (degrees_per_pixel_x, degrees_per_pixel_y)

    Returns:
        (minx, miny, maxx, maxy) in EPSG:4326 degrees
    """
    degrees_per_pixel_x, degrees_per_pixel_y = degrees_per_pixel

    # Calculate tile bounds in EPSG:4326
    minx = target_bounds[0] + (pixel_window["col_off"] * degrees_per_pixel_x)
    maxy = target_bounds[3] - (pixel_window["row_off"] * degrees_per_pixel_y)  # Y inverted

    maxx = minx + (pixel_window["width"] * degrees_per_pixel_x)
    miny = maxy - (pixel_window["height"] * degrees_per_pixel_y)

    return (minx, miny, maxx, maxy)


def create_geojson_feature(
    tile: Dict[str, Any],
    bounds_4326: Tuple[float, float, float, float]
) -> Dict[str, Any]:
    """
    Create GeoJSON feature for tile.

    Args:
        tile: Tile definition with id, pixel_window, etc.
        bounds_4326: Geographic bounds in EPSG:4326

    Returns:
        GeoJSON Feature dict with:
            - type: "Feature"
            - id: Tile ID (sequential)
            - geometry: Polygon in EPSG:4326
            - properties: All tile metadata (tile_id, row, col, pixel_window, bounds, etc.)
    """
    rasterio, transform_bounds, box, mapping = _lazy_imports()

    minx, miny, maxx, maxy = bounds_4326

    # Create bounding box geometry (always EPSG:4326 per GeoJSON spec)
    geom = box(minx, miny, maxx, maxy)

    return {
        "type": "Feature",
        "id": tile["id"],
        "geometry": mapping(geom),
        "properties": {
            "tile_id": tile["tile_id"],
            "task_id": tile["id"],  # Corresponds to task number
            "row": tile["row"],
            "col": tile["col"],
            "pixel_window": tile["pixel_window"],
            "bounds_4326": [minx, miny, maxx, maxy],
            "target_width_pixels": tile["target_width_pixels"],
            "target_height_pixels": tile["target_height_pixels"],
            "crs_target": "EPSG:4326"
        }
    }


def generate_tiling_scheme_from_raster(
    raster_path: str,
    tile_size: Optional[int] = None,
    overlap: Optional[int] = None,
    band_names: Optional[Dict[int, str]] = None,
    target_crs: str = "EPSG:4326"
) -> Dict[str, Any]:
    """
    Generate complete tiling scheme GeoJSON from raster file.

    Internal helper used by generate_tiling_scheme() after downloading blob.

    Args:
        raster_path: Path to input raster (local or blob storage)
        tile_size: Tile size in pixels (None = auto-calculate based on bands/bit-depth, default: None)
        overlap: Overlap in pixels (None = use 512px default for COG alignment)

    Returns:
        GeoJSON FeatureCollection dict with metadata and features
    """
    rasterio, transform_bounds, box, mapping = _lazy_imports()

    with rasterio.open(raster_path) as src:
        # Source raster info
        src_crs = src.crs.to_string() if src.crs else "UNKNOWN"
        src_bounds = src.bounds
        src_width = src.width
        src_height = src.height
        src_res = src.res

        # Extract raster metadata for COG creation (Stage 3)
        actual_band_count = src.count
        dtype = src.dtypes[0]  # First band dtype (all bands usually same)

        # =================================================================
        # AUTO-DETECTION: Detect raster type to determine optimal band_names
        # Added 01 DEC 2025 - Fixes issue where RGB images got wrong bands
        # =================================================================
        from services.raster_validation import _detect_raster_type
        from jobs.raster_mixin import RasterMixin

        raster_type_result = _detect_raster_type(src, user_type="auto")
        detected_type = raster_type_result.get("detected_type", "unknown")
        detection_confidence = raster_type_result.get("confidence", "LOW")

        # Auto-determine band_names if not provided
        auto_band_names = RasterMixin._get_default_band_names(detected_type, actual_band_count)

        # If user didn't provide band_names, use auto-detected
        if not band_names or (isinstance(band_names, dict) and len(band_names) == 0):
            band_names = auto_band_names
            if band_names:
                logger.info(f"🎯 Auto-detected raster type: {detected_type} ({detection_confidence}) → band_names: {band_names}")
            else:
                logger.info(f"🎯 Auto-detected raster type: {detected_type} ({detection_confidence}) → processing all {actual_band_count} bands")
        else:
            logger.info(f"📋 Using user-provided band_names: {band_names} (auto-detected: {detected_type})")

        # Determine bit depth from dtype for tile size calculation
        dtype_str = str(dtype).lower()
        if 'uint8' in dtype_str or 'int8' in dtype_str:
            bit_depth = 8
        elif 'uint16' in dtype_str or 'int16' in dtype_str:
            bit_depth = 16
        elif 'uint32' in dtype_str or 'int32' in dtype_str or 'float32' in dtype_str:
            bit_depth = 32
        else:
            bit_depth = 64  # float64 (rare)

        # Use requested band count for tile size calculation (not actual file band count)
        # This ensures tiles are appropriately sized for the data we'll actually read
        # band_names is a dict: {5: 'Red', 3: 'Green', 2: 'Blue'}
        if band_names and isinstance(band_names, dict) and len(band_names) > 0:
            band_count = len(band_names)
            band_list = ', '.join(f"{idx}:{name}" for idx, name in sorted(band_names.items()))
            logger.info(f"📊 Using requested band count for tile sizing: {band_count} bands [{band_list}] (file has {actual_band_count})")
        else:
            band_count = actual_band_count
            logger.info(f"📊 Using full raster band count for tile sizing: {band_count} bands")

        # Calculate optimal tile size if not explicitly provided
        # tile_size=None means auto-calculate based on raster characteristics
        if tile_size is None:
            try:
                calculated_tile_size, calculated_overlap = calculate_optimal_tile_size(
                    band_count=band_count,
                    bit_depth=bit_depth
                )
                logger.info(f"📐 Auto-calculated tile size: {calculated_tile_size}px ({calculated_tile_size//512}×512 blocks) for {band_count}-band {bit_depth}-bit data (target: ~300MB per tile)")
                tile_size = calculated_tile_size
                overlap = calculated_overlap
            except Exception as e:
                # Fallback to safe default if calculation fails
                logger.warning(f"⚠️ Auto-calculation failed ({e}), using fallback: 20480px (40×512 blocks)")
                tile_size = 20480  # 40×512 blocks = ~1.2GB for 3-band 8-bit
                overlap = 512

        # If user provided tile_size but no overlap, use 512 for COG alignment
        if overlap is None:
            overlap = 512

        # Calculate target resolution in specified target CRS
        target_bounds, target_width, target_height, degrees_per_pixel = calculate_target_resolution(
            src_crs, src_bounds, src_width, src_height, target_crs
        )

        # Calculate grid with optimal/provided tile size
        grid = calculate_tile_grid(target_width, target_height, tile_size, overlap)

        # Generate tile windows
        tiles = generate_tile_windows(target_width, target_height, tile_size, overlap)

        # Create GeoJSON features
        features = []
        for tile in tiles:
            bounds_4326 = calculate_tile_bounds_4326(
                tile["pixel_window"],
                target_bounds,
                degrees_per_pixel
            )
            feature = create_geojson_feature(tile, bounds_4326)
            features.append(feature)

        # Create FeatureCollection
        geojson = {
            "type": "FeatureCollection",
            "metadata": {
                "source_crs": src_crs,
                "source_bounds_native": list(src_bounds),
                "source_dimensions": [src_width, src_height],
                "source_resolution": list(src_res),

                "target_crs": target_crs,
                "target_bounds": list(target_bounds),
                "target_dimensions": [target_width, target_height],
                "target_resolution": list(degrees_per_pixel),

                "tile_size_pixels": tile_size,
                "overlap_pixels": overlap,
                "cog_blocksize": 512,
                "grid": grid,

                "total_tiles": len(features),

                # Raster metadata for COG creation (Stage 3)
                # Auto-detection added 01 DEC 2025
                "raster_metadata": {
                    "band_count": band_count,
                    "actual_band_count": actual_band_count,
                    "data_type": str(dtype),
                    "detected_type": detected_type,
                    "detection_confidence": detection_confidence,
                    "auto_band_names": auto_band_names,
                    "used_band_names": band_names,
                },

                "architecture": {
                    "output_space_tiling": True,
                    "perfect_alignment": "Tiles defined in EPSG:4326 ensure no seams after reprojection",
                    "overlap_matches_cog_blocksize": True
                }
            },
            "features": features
        }

        return geojson


def generate_tiling_scheme(params: dict) -> dict:
    """
    Generate tiling scheme for large raster - Stage 1 of Big Raster ETL.

    Downloads raster from blob storage, generates GeoJSON tiling scheme in
    EPSG:4326 output space, uploads tiling scheme to blob storage.

    Args:
        params: Task parameters dict with:
            - container_name (str, REQUIRED): Bronze container name
            - blob_name (str, REQUIRED): Bronze blob name
            - tile_size (int, optional): Tile size in pixels (None = auto-calculate based on bands/bit-depth)
            - overlap (int, optional): Overlap in pixels (default: 512)
            - output_container (str, optional): Output container (default: same as source)
            - output_blob_name (str, optional): Output blob name (default: <source>_tiling_scheme.geojson)

    Returns:
        dict: {
            "success": bool,
            "result": {
                "tiling_scheme_blob": str,       # ← Output tiling scheme path
                "tiling_scheme_container": str,  # ← Container name
                "total_tiles": int,              # ← Number of tiles generated
                "grid": dict,                    # ← Grid metadata (rows, cols, etc.)
                "source_blob": str,
                "source_container": str,
                "source_crs": str,
                "target_crs": str,
                "target_bounds": list,           # ← [minx, miny, maxx, maxy] in EPSG:4326
                "target_dimensions": list,       # ← [width, height] in pixels
                "target_resolution": list,       # ← [degrees_per_pixel_x, degrees_per_pixel_y]
                "processing_time_seconds": float
            },
            "error": str (if success=False)
        }
    """
    from infrastructure.blob import BlobRepository

    start_time = datetime.now(timezone.utc)

    try:
        # Extract parameters
        container_name = params.get("container_name")
        blob_name = params.get("blob_name")
        tile_size = params.get("tile_size")  # None = auto-calculate
        overlap = params.get("overlap", 512)
        output_container = params.get("output_container", container_name)
        output_blob_name = params.get("output_blob_name")
        target_crs = params.get("target_crs", "EPSG:4326")  # Target CRS for tiling scheme

        # Validate band_names with Pydantic (strict validation, no fallbacks)
        band_names_raw = params.get("band_names")  # None if not provided
        if band_names_raw is not None:
            try:
                band_names_model = BandNames(mapping=band_names_raw)
                band_names = band_names_model.mapping  # dict[int, str] with int keys
                logger.debug(f"✅ band_names validated: {band_names}")
            except ValidationError as e:
                error_msg = e.errors()[0]['msg'] if e.errors() else str(e)
                error_str = f"Invalid band_names parameter: {error_msg}"
                logger.error(f"❌ {error_str}")
                return {"success": False, "error": error_str}
        else:
            band_names = {}  # Empty dict = use all bands for tile size calculation
            logger.debug(f"✅ No band_names provided, will use all bands for tile size calculation")

        if not container_name or not blob_name:
            return {
                "success": False,
                "error": "Missing required parameters: container_name, blob_name"
            }

        # Generate default output blob name if not provided
        if not output_blob_name:
            blob_stem = Path(blob_name).stem
            output_blob_name = f"{blob_stem}_tiling_scheme.geojson"

        # Initialize repositories for input (bronze) and output (silver)
        # Input files come from bronze zone - use bronze repo for SAS URL generation
        # Output (tiling scheme) goes to silver zone where extract_tiles expects it
        bronze_repo = BlobRepository.for_zone("bronze")
        silver_repo = BlobRepository.for_zone("silver")

        # Generate SAS URL for VSI access (2-hour expiry for processing buffer)
        logger.info(f"🌐 Generating SAS URL for VSI access: {blob_name}")
        sas_url = bronze_repo.get_blob_url_with_sas(
            container_name=container_name,
            blob_name=blob_name,
            hours=2  # 2-hour buffer for large file processing
        )

        # Create VSI path for GDAL to access blob via HTTP
        vsi_path = f"/vsicurl/{sas_url}"
        logger.info(f"✅ VSI path created: /vsicurl/https://...")
        logger.debug(f"   Reading raster directly from Azure Blob Storage (no /tmp download)")

        # Generate tiling scheme using VSI (no temporary file needed)
        logger.info(f"🔲 Generating tiling scheme via VSI...")
        try:
            geojson = generate_tiling_scheme_from_raster(
                raster_path=vsi_path,
                tile_size=tile_size,
                overlap=overlap,
                band_names=band_names,
                target_crs=target_crs
            )
        except Exception as e:
            # VSI-specific error handling
            error_str = str(e)
            if "HTTP" in error_str or "404" in error_str or "403" in error_str:
                raise ValueError(f"VSI HTTP error accessing blob: {error_str}. Check SAS URL validity and blob existence.")
            elif "timeout" in error_str.lower():
                raise ValueError(f"VSI timeout accessing blob: {error_str}. Blob may be too large or network issues.")
            else:
                raise  # Re-raise other errors

        # Upload tiling scheme to silver zone blob storage
        # Tiling scheme is written to silver zone where extract_tiles reads from
        logger.info(f"📤 Uploading tiling scheme to silver zone: {output_container}/{output_blob_name}")
        geojson_bytes = json.dumps(geojson, indent=2).encode('utf-8')
        silver_repo.write_blob(
            container=output_container,
            blob_path=output_blob_name,
            data=geojson_bytes,
            content_type="application/geo+json"
        )

        # Calculate processing time
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info(f"✅ Tiling scheme generated: {geojson['metadata']['total_tiles']} tiles")

        return {
            "success": True,
            "result": {
                "tiling_scheme_blob": output_blob_name,
                "tiling_scheme_container": output_container,
                "total_tiles": geojson['metadata']['total_tiles'],
                "grid": geojson['metadata']['grid'],
                "source_blob": blob_name,
                "source_container": container_name,
                "source_crs": geojson['metadata']['source_crs'],
                "target_crs": geojson['metadata']['target_crs'],
                "target_bounds": geojson['metadata']['target_bounds'],
                "target_dimensions": geojson['metadata']['target_dimensions'],
                "target_resolution": geojson['metadata']['target_resolution'],
                "processing_time_seconds": round(processing_time, 2),
                # Raster metadata with auto-detection (01 DEC 2025)
                "raster_metadata": geojson['metadata']['raster_metadata']
            }
        }

    except Exception as e:
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        error_msg = f"Failed to generate tiling scheme: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"❌ ERROR: {error_msg}")

        return {
            "success": False,
            "error": error_msg,
            "processing_time_seconds": round(processing_time, 2)
        }
