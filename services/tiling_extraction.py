# ============================================================================
# CLAUDE CONTEXT - SERVICE - TILING EXTRACTION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Sequential tile extraction with progress reporting
# PURPOSE: Extract tiles from large rasters following tiling scheme (Stage 2)
# LAST_REVIEWED: 24 OCT 2025
# EXPORTS: extract_tiles() - Main handler function
# INTERFACES: Handler pattern for task execution (Stage 2 of raster tiling)
# PYDANTIC_MODELS: None (returns dict)
# DEPENDENCIES: rasterio, azure-storage-blob, config
# SOURCE: Bronze container rasters, tiling scheme GeoJSON from Stage 1
# SCOPE: Stage 2 of Big Raster ETL workflow (sequential extraction)
# VALIDATION: Input validation via rasterio, bounds validation
# PATTERNS: Handler pattern, sequential processing with progress updates
# ENTRY_POINTS: Called by task processor with parameters dict
# ARCHITECTURE: Extracts raw tiles in source CRS (reprojection happens in Stage 3)
# ============================================================================

"""
Tiling Extraction Service - Stage 2 of Big Raster ETL

Extracts tiles from large rasters following the tiling scheme generated in Stage 1.

Critical Architectural Pattern:
- Stage 1 creates ONE task (generate tiling scheme)
- Stage 2 is ONE LONG-RUNNING task that extracts ALL tiles sequentially
- Stage 3 creates N tasks (one per tile) for parallel COG conversion + reprojection
- Stage 4 creates MosaicJSON + STAC metadata

Why Sequential Extraction?:
1. **Azure Functions Constraint**: 10-minute timeout
2. **Sequential Reads**: Sequential disk I/O is MUCH faster than random access
3. **Progress Reporting**: Single task can update metadata with progress
4. **Simplicity**: No coordination needed between tasks

Example:
    A 11 GB raster with 204 tiles:
    - Stage 1: Generate tiling scheme (1 task)
    - Stage 2: Extract 204 tiles sequentially (~3 minutes, THIS service)
    - Stage 3: Convert 204 tiles to COG in parallel (204 tasks)
    - Stage 4: Generate MosaicJSON + STAC (1 task)

Author: Robert and Geospatial Claude Legion
Date: 24 OCT 2025
"""

import json
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Lazy imports for Azure environment compatibility
def _lazy_imports():
    """Lazy import to avoid module-level import failures."""
    import rasterio
    from rasterio.windows import Window
    return rasterio, Window


def extract_tiles_from_raster(
    raster_path: str,
    tiling_scheme: Dict[str, Any],
    output_dir: Path,
    progress_callback: Optional[callable] = None
) -> List[Path]:
    """
    Extract all tiles from raster following tiling scheme.

    Internal helper used by extract_tiles() after downloading raster + tiling scheme.

    Args:
        raster_path: Path to source raster
        tiling_scheme: GeoJSON FeatureCollection from Stage 1
        output_dir: Directory to write tiles
        progress_callback: Optional callback(tile_idx, total_tiles, tile_id, elapsed_sec)

    Returns:
        List of extracted tile paths
    """
    rasterio, Window = _lazy_imports()

    tiles = tiling_scheme['features']
    total_tiles = len(tiles)
    start_time = datetime.now(timezone.utc)
    extracted_tiles = []

    print(f"📦 Extracting {total_tiles} tiles from raster...")

    with rasterio.open(raster_path) as src:
        print(f"✅ Opened source raster: {src.width} × {src.height} pixels")
        print(f"   CRS: {src.crs}")
        print("")

        for i, tile_feature in enumerate(tiles):
            props = tile_feature['properties']
            tile_id = props['tile_id']
            pw = props['pixel_window']

            # Create rasterio window from pixel_window
            window = Window(
                col_off=pw['col_off'],
                row_off=pw['row_off'],
                width=pw['width'],
                height=pw['height']
            )

            # Read tile data
            tile_data = src.read(window=window)
            tile_transform = src.window_transform(window)

            # Prepare output path
            output_path = output_dir / f"{tile_id}.tif"

            # Write tile (in source CRS - no reprojection yet)
            profile = src.profile.copy()
            profile.update({
                'width': pw['width'],
                'height': pw['height'],
                'transform': tile_transform
            })

            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(tile_data)

            extracted_tiles.append(output_path)

            # Progress reporting
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            progress = (i + 1) / total_tiles
            eta = (elapsed / progress) - elapsed if progress > 0 else 0

            # Log every 10 tiles or at completion
            if (i + 1) % 10 == 0 or (i + 1) == total_tiles:
                print(f"   [{i+1:3d}/{total_tiles:3d}] {tile_id:15s} [{progress*100:5.1f}% - ETA: {eta:5.1f}s]")

            # Call progress callback if provided
            if progress_callback:
                progress_callback(i + 1, total_tiles, tile_id, elapsed)

    total_duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    print(f"\n✅ Extraction complete: {total_tiles} tiles in {total_duration:.1f} seconds")

    return extracted_tiles


def extract_tiles(params: dict) -> dict:
    """
    Extract tiles from large raster - Stage 2 of Big Raster ETL.

    Downloads raster and tiling scheme from blob storage, extracts all tiles
    sequentially, uploads tiles to blob storage.

    CRITICAL: This is a LONG-RUNNING task that extracts ALL tiles sequentially.
    - Sequential I/O is MUCH faster than parallel random access
    - Progress is reported via task metadata updates
    - Stage 3 will create N parallel tasks for COG conversion

    Args:
        params: Task parameters dict with:
            - container_name (str, REQUIRED): Bronze container name
            - blob_name (str, REQUIRED): Bronze blob name
            - tiling_scheme_blob (str, REQUIRED): Tiling scheme blob name (from Stage 1)
            - tiling_scheme_container (str, optional): Tiling scheme container (default: same as source)
            - output_container (str, optional): Output container (default: same as source)
            - output_prefix (str, optional): Output blob prefix (default: "tiles/<source_stem>/")
            - task_id (str, optional): Task ID for metadata progress updates
            - repository (object, optional): Repository instance for metadata updates

    Returns:
        dict: {
            "success": bool,
            "result": {
                "tiles_blob_prefix": str,        # ← Output tile blob prefix
                "tiles_container": str,          # ← Container name
                "total_tiles": int,              # ← Number of tiles extracted
                "tile_blobs": list,              # ← List of tile blob names
                "source_blob": str,
                "source_container": str,
                "tiling_scheme_blob": str,
                "source_crs": str,
                "extraction_time_seconds": float,
                "upload_time_seconds": float,
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
        tiling_scheme_blob = params.get("tiling_scheme_blob")
        tiling_scheme_container = params.get("tiling_scheme_container", container_name)
        output_container = params.get("output_container", container_name)
        output_prefix = params.get("output_prefix")
        task_id = params.get("task_id")
        repository = params.get("repository")

        if not container_name or not blob_name or not tiling_scheme_blob:
            return {
                "success": False,
                "error": "Missing required parameters: container_name, blob_name, tiling_scheme_blob"
            }

        # Generate default output prefix if not provided
        if not output_prefix:
            blob_stem = Path(blob_name).stem
            output_prefix = f"tiles/{blob_stem}/"

        # Initialize repository
        blob_repo = BlobRepository()

        # Download raster to temporary file (streaming to avoid OOM)
        print(f"📥 Streaming raster to disk: {blob_name}")
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp_raster:
            tmp_raster_path = tmp_raster.name
            # Stream in 128MB chunks (optimal for large files on Azure Functions)
            # 128MB = 3.7% of EP1 RAM, safe and 30x faster than 4MB default
            chunk_size = 128 * 1024 * 1024  # 128 MB
            for chunk in blob_repo.read_blob_chunked(container_name, blob_name, chunk_size=chunk_size):
                tmp_raster.write(chunk)

        # Download tiling scheme
        print(f"📥 Downloading tiling scheme: {tiling_scheme_blob}")
        tiling_scheme_json = blob_repo.read_blob(tiling_scheme_container, tiling_scheme_blob)
        tiling_scheme = json.loads(tiling_scheme_json)

        # Create temporary directory for tiles
        tmp_tiles_dir = Path(tempfile.mkdtemp(prefix="tiles_"))

        try:
            # Define progress callback for metadata updates
            def progress_callback(tile_idx, total_tiles, tile_id, elapsed_sec):
                """Update task metadata with progress."""
                if repository and task_id:
                    progress_metadata = {
                        "extraction_progress": {
                            "tiles_extracted": tile_idx,
                            "total_tiles": total_tiles,
                            "current_tile": tile_id,
                            "elapsed_seconds": round(elapsed_sec, 2),
                            "percent_complete": round((tile_idx / total_tiles) * 100, 2)
                        }
                    }
                    try:
                        repository.update_task_metadata(task_id, progress_metadata, merge=True)
                    except Exception as e:
                        print(f"⚠️  Failed to update metadata: {e}")

            # Extract tiles
            extraction_start = datetime.now(timezone.utc)
            extracted_tiles = extract_tiles_from_raster(
                raster_path=tmp_raster_path,
                tiling_scheme=tiling_scheme,
                output_dir=tmp_tiles_dir,
                progress_callback=progress_callback
            )
            extraction_time = (datetime.now(timezone.utc) - extraction_start).total_seconds()

            # Upload tiles to blob storage
            print(f"\n📤 Uploading {len(extracted_tiles)} tiles to {output_container}/{output_prefix}")
            upload_start = datetime.now(timezone.utc)
            tile_blobs = []

            for i, tile_path in enumerate(extracted_tiles):
                tile_name = tile_path.name
                blob_name_full = f"{output_prefix}{tile_name}"

                with open(tile_path, 'rb') as tile_data:
                    blob_repo.write_blob(
                        container=output_container,
                        blob_path=blob_name_full,
                        data=tile_data,
                        overwrite=True,
                        content_type="image/tiff"
                    )

                tile_blobs.append(blob_name_full)

                # Log upload progress every 20 tiles
                if (i + 1) % 20 == 0 or (i + 1) == len(extracted_tiles):
                    progress = (i + 1) / len(extracted_tiles)
                    print(f"   Uploaded: [{i+1:3d}/{len(extracted_tiles):3d}] ({progress*100:5.1f}%)")

            upload_time = (datetime.now(timezone.utc) - upload_start).total_seconds()

            # Calculate total processing time
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            print(f"\n✅ Tile extraction complete!")
            print(f"   Extracted: {len(extracted_tiles)} tiles in {extraction_time:.1f}s")
            print(f"   Uploaded: {len(tile_blobs)} tiles in {upload_time:.1f}s")
            print(f"   Total: {processing_time:.1f}s")

            return {
                "success": True,
                "result": {
                    "tiles_blob_prefix": output_prefix,
                    "tiles_container": output_container,
                    "total_tiles": len(tile_blobs),
                    "tile_blobs": tile_blobs,
                    "source_blob": blob_name,
                    "source_container": container_name,
                    "tiling_scheme_blob": tiling_scheme_blob,
                    "source_crs": tiling_scheme['metadata']['source_crs'],
                    # Pass through raster metadata from Stage 1 for Stage 3 COG creation
                    "raster_metadata": tiling_scheme['metadata'].get('raster_metadata', {}),
                    "extraction_time_seconds": round(extraction_time, 2),
                    "upload_time_seconds": round(upload_time, 2),
                    "processing_time_seconds": round(processing_time, 2)
                }
            }

        finally:
            # Clean up temporary files
            for tile_path in tmp_tiles_dir.glob("*.tif"):
                tile_path.unlink(missing_ok=True)
            tmp_tiles_dir.rmdir()
            Path(tmp_raster_path).unlink(missing_ok=True)

    except Exception as e:
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        error_msg = f"Failed to extract tiles: {str(e)}\n{traceback.format_exc()}"
        print(f"❌ ERROR: {error_msg}")

        return {
            "success": False,
            "error": error_msg,
            "processing_time_seconds": round(processing_time, 2)
        }
