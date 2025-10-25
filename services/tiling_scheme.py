# ============================================================================
# CLAUDE CONTEXT - SERVICE - TILING SCHEME GENERATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Tiling scheme generation for large rasters
# PURPOSE: Generate GeoJSON tiling schemes in EPSG:4326 output space
# LAST_REVIEWED: 24 OCT 2025
# EXPORTS: generate_tiling_scheme() - Main handler function
# INTERFACES: Handler pattern for task execution (Stage 1 of raster tiling)
# PYDANTIC_MODELS: None (returns dict with GeoJSON structure)
# DEPENDENCIES: rasterio, shapely, azure-storage-blob, config
# SOURCE: Bronze container rasters, blob storage
# SCOPE: Stage 1 of Big Raster ETL workflow (5-30 GB rasters)
# VALIDATION: Input validation via rasterio, bounds validation
# PATTERNS: Handler pattern, output-space tiling architecture
# ENTRY_POINTS: Called by task processor with parameters dict
# ARCHITECTURE: Tiles defined in EPSG:4326 output space for perfect alignment
# ============================================================================

"""
Tiling Scheme Generation Service - Stage 1 of Big Raster ETL

Generates GeoJSON tiling schemes for large rasters (1-30 GB) in EPSG:4326 output space.

Critical Architecture Decision:
- Tiles are defined in EPSG:4326 OUTPUT space (not source CRS)
- This ensures perfect tile alignment after reprojection (no seams)
- Rio-cogeo handles source pixel sampling automatically via WarpedVRT
- 512-pixel overlap aligns with COG 512×512 internal block structure

Example:
    A 11 GB Web Mercator raster becomes 204 tiles:
    - 17×12 grid in EPSG:4326 output space
    - Each tile: 5000×5000 pixels with 512px overlap
    - Results in 204 tasks for Stage 2 (parallel extraction)

Author: Robert and Geospatial Claude Legion
Date: 24 OCT 2025
"""

import json
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Lazy imports for Azure environment compatibility
def _lazy_imports():
    """Lazy import to avoid module-level import failures."""
    import rasterio
    from rasterio.warp import transform_bounds
    from shapely.geometry import box, mapping
    return rasterio, transform_bounds, box, mapping


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
            - tile_id: Semantic tile ID (tile_0_0, tile_0_1, ...)
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
            tile = {
                "id": tile_id,
                "tile_id": f"tile_{row}_{col}",
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
    tile_size: int = 5000,
    overlap: int = 512
) -> Dict[str, Any]:
    """
    Generate complete tiling scheme GeoJSON from raster file.

    Internal helper used by generate_tiling_scheme() after downloading blob.

    Args:
        raster_path: Path to input raster (local or blob storage)
        tile_size: Tile size in pixels (default: 5000)
        overlap: Overlap in pixels (default: 512, matches COG blocksize)

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
        band_count = src.count
        dtype = src.dtypes[0]  # First band dtype (all bands usually same)

        # Calculate target resolution in EPSG:4326
        target_bounds, target_width, target_height, degrees_per_pixel = calculate_target_resolution(
            src_crs, src_bounds, src_width, src_height
        )

        # Calculate grid
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

                "target_crs": "EPSG:4326",
                "target_bounds": list(target_bounds),
                "target_dimensions": [target_width, target_height],
                "target_resolution": list(degrees_per_pixel),

                "tile_size_pixels": tile_size,
                "overlap_pixels": overlap,
                "cog_blocksize": 512,
                "grid": grid,

                "total_tiles": len(features),

                # Raster metadata for COG creation (Stage 3)
                "raster_metadata": {
                    "band_count": band_count,
                    "data_type": str(dtype),
                    "detected_type": "unknown"  # No auto-detection in tiling stage
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
            - tile_size (int, optional): Tile size in pixels (default: 5000)
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
        tile_size = params.get("tile_size", 5000)
        overlap = params.get("overlap", 512)
        output_container = params.get("output_container", container_name)
        output_blob_name = params.get("output_blob_name")

        if not container_name or not blob_name:
            return {
                "success": False,
                "error": "Missing required parameters: container_name, blob_name"
            }

        # Generate default output blob name if not provided
        if not output_blob_name:
            blob_stem = Path(blob_name).stem
            output_blob_name = f"{blob_stem}_tiling_scheme.geojson"

        # Initialize repository
        blob_repo = BlobRepository()

        # Download raster to temporary file (streaming to avoid OOM)
        print(f"📥 Streaming raster to disk: {blob_name}")
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp_file:
            tmp_path = tmp_file.name
            # Stream in 128MB chunks (optimal for large files on Azure Functions)
            # 128MB = 3.7% of EP1 RAM, safe and 30x faster than 4MB default
            chunk_size = 128 * 1024 * 1024  # 128 MB
            for chunk in blob_repo.read_blob_chunked(container_name, blob_name, chunk_size=chunk_size):
                tmp_file.write(chunk)

        try:
            # Generate tiling scheme
            print(f"🔲 Generating tiling scheme...")
            geojson = generate_tiling_scheme_from_raster(
                raster_path=tmp_path,
                tile_size=tile_size,
                overlap=overlap
            )

            # Upload tiling scheme to blob storage
            print(f"📤 Uploading tiling scheme: {output_blob_name}")
            geojson_bytes = json.dumps(geojson, indent=2).encode('utf-8')
            blob_repo.write_blob(
                container=output_container,
                blob_path=output_blob_name,
                data=geojson_bytes,
                content_type="application/geo+json"
            )

            # Calculate processing time
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            print(f"✅ Tiling scheme generated: {geojson['metadata']['total_tiles']} tiles")

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
                    "processing_time_seconds": round(processing_time, 2)
                }
            }

        finally:
            # Clean up temporary file
            Path(tmp_path).unlink(missing_ok=True)

    except Exception as e:
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        error_msg = f"Failed to generate tiling scheme: {str(e)}\n{traceback.format_exc()}"
        print(f"❌ ERROR: {error_msg}")

        return {
            "success": False,
            "error": error_msg,
            "processing_time_seconds": round(processing_time, 2)
        }
