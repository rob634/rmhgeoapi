# ============================================================================
# CLAUDE CONTEXT - SERVICE - RASTER COG CREATION
# ============================================================================
# PURPOSE: Create Cloud Optimized GeoTIFFs with optional reprojection
# EXPORTS: create_cog() handler function
# INTERFACES: Handler pattern for task execution
# PYDANTIC_MODELS: None (returns dict)
# DEPENDENCIES: rio-cogeo, rasterio, azure blob storage, config
# SOURCE: Bronze container rasters, validation results from Stage 1
# SCOPE: Stage 2 of raster processing pipeline
# VALIDATION: Uses validation results to auto-select COG settings
# PATTERNS: Handler pattern, single-pass reproject + COG
# ENTRY_POINTS: Called by task processor with parameters dict
# ============================================================================

"""
Raster COG Creation Service - Stage 2 of Raster Pipeline

Creates Cloud Optimized GeoTIFFs with optional reprojection using rio-cogeo.

Key Innovation: Single-pass reprojection + COG creation
- rio-cogeo.cog_translate() does both operations in one pass
- No intermediate storage needed for small files
- Auto-selects optimal compression and resampling based on raster type

Type-Specific Optimizations:
- RGB: JPEG compression (97% reduction), cubic resampling
- RGBA (drones): WebP compression (supports alpha), cubic resampling
- DEM: LERC+DEFLATE (lossless scientific), average overviews, bilinear reproject
- Categorical: DEFLATE, mode overviews (preserves classes), nearest reproject
- Multispectral: DEFLATE (lossless), average overviews, bilinear reproject
"""

import sys
import os
import tempfile
from typing import Any, Dict, Optional
from datetime import datetime, timezone

# Lazy imports for Azure environment compatibility
def _lazy_imports():
    """Lazy import to avoid module-level import failures."""
    import rasterio
    from rasterio.enums import Resampling
    from rio_cogeo.cogeo import cog_translate
    from rio_cogeo.profiles import cog_profiles
    return rasterio, Resampling, cog_translate, cog_profiles


def create_cog(params: dict) -> dict:
    """
    Create Cloud Optimized GeoTIFF with optional reprojection.

    Stage 2 of raster processing pipeline. Performs:
    - Single-pass reprojection + COG creation (if CRS != target)
    - Auto-selects optimal compression based on raster type
    - Auto-selects optimal resampling methods
    - Downloads from bronze, creates COG, uploads to silver
    - Cleans up temporary files

    Args:
        params: Task parameters dict with:
            - blob_url: Azure blob URL for bronze raster (with SAS token)
            - source_crs: CRS from validation stage
            - target_crs: Target CRS (default: EPSG:4326)
            - raster_type: Detected raster type from validation
            - optimal_cog_settings: Recommended settings from validation
            - compression: (Optional) User override for compression
            - jpeg_quality: (Optional) JPEG quality (1-100)
            - overview_resampling: (Optional) User override
            - reproject_resampling: (Optional) User override
            - output_blob_name: Silver container blob path
            - container: Bronze container name
            - blob_name: Bronze blob name

    Returns:
        dict: {
            "success": True/False,
            "result": {...COG metadata...},
            "error": "ERROR_CODE" (if failed),
            "message": "Error description" (if failed)
        }
    """

    print(f"🏗️ COG CREATION: Starting COG creation", file=sys.stderr, flush=True)

    # Extract parameters
    blob_url = params.get('blob_url')
    source_crs = params.get('source_crs')
    target_crs = params.get('target_crs', 'EPSG:4326')
    raster_type = params.get('raster_type', {}).get('detected_type', 'unknown')
    optimal_settings = params.get('raster_type', {}).get('optimal_cog_settings', {})

    # User overrides or optimal settings
    compression = params.get('compression') or optimal_settings.get('compression', 'deflate')
    jpeg_quality = params.get('jpeg_quality', 85)
    overview_resampling = params.get('overview_resampling') or optimal_settings.get('overview_resampling', 'cubic')
    reproject_resampling = params.get('reproject_resampling') or optimal_settings.get('reproject_resampling', 'cubic')

    output_blob_name = params.get('output_blob_name')

    if not all([blob_url, source_crs, output_blob_name]):
        return {
            "success": False,
            "error": "MISSING_PARAMETER",
            "message": "blob_url, source_crs, and output_blob_name parameters are required"
        }

    print(f"📊 COG CREATION: Type: {raster_type}, Compression: {compression}", file=sys.stderr, flush=True)
    print(f"📍 COG CREATION: CRS: {source_crs} → {target_crs}", file=sys.stderr, flush=True)

    # Lazy import dependencies
    try:
        rasterio, Resampling, cog_translate, cog_profiles = _lazy_imports()
    except ImportError as e:
        return {
            "success": False,
            "error": "IMPORT_ERROR",
            "message": f"Failed to import rio-cogeo: {e}"
        }

    # Import blob storage
    try:
        from infrastructure.blob import BlobRepository
    except ImportError as e:
        return {
            "success": False,
            "error": "IMPORT_ERROR",
            "message": f"Failed to import BlobRepository: {e}"
        }

    # Create temp directory for processing
    temp_dir = tempfile.mkdtemp(prefix="cog_")
    local_output = os.path.join(temp_dir, "output_cog.tif")

    try:
        start_time = datetime.now(timezone.utc)

        # Get COG profile for compression type
        try:
            cog_profile = cog_profiles.get(compression)
        except KeyError:
            print(f"⚠️ COG CREATION: Unknown compression '{compression}', using deflate", file=sys.stderr, flush=True)
            cog_profile = cog_profiles.get('deflate')

        # Add JPEG quality if using JPEG compression
        if compression == "jpeg":
            cog_profile["QUALITY"] = jpeg_quality

        # Determine if reprojection needed
        needs_reprojection = (str(source_crs) != str(target_crs))

        # Configure reprojection if needed
        if needs_reprojection:
            print(f"🔄 COG CREATION: Reprojection needed: {source_crs} → {target_crs}", file=sys.stderr, flush=True)
            config = {
                "dst_crs": target_crs,
                "resampling": getattr(Resampling, reproject_resampling),
            }
        else:
            print(f"✓ COG CREATION: No reprojection needed (already {target_crs})", file=sys.stderr, flush=True)
            config = {}

        # Get resampling enum for overviews
        try:
            overview_resampling_enum = getattr(Resampling, overview_resampling)
        except AttributeError:
            print(f"⚠️ COG CREATION: Unknown resampling '{overview_resampling}', using cubic", file=sys.stderr, flush=True)
            overview_resampling_enum = Resampling.cubic

        # Get in_memory setting from config
        from config import get_config
        config_obj = get_config()
        in_memory = config_obj.raster_cog_in_memory

        print(f"🎯 COG CREATION: Creating COG with {compression} compression...", file=sys.stderr, flush=True)
        print(f"💾 COG CREATION: Processing mode: {'in-memory (RAM)' if in_memory else 'disk-based (/tmp SSD)'}", file=sys.stderr, flush=True)

        # Create COG (with optional reprojection in single pass)
        cog_translate(
            blob_url,
            local_output,
            cog_profile,
            config=config,
            overview_level=None,  # Auto-calculate optimal levels
            overview_resampling=overview_resampling_enum,
            in_memory=in_memory,  # Configurable: True (default) for small files, False for large
            quiet=False,
        )

        # Get output file info
        output_size_mb = os.path.getsize(local_output) / (1024 * 1024)

        with rasterio.open(local_output) as dst:
            output_shape = dst.shape
            output_bounds = dst.bounds
            output_crs = dst.crs
            overviews = dst.overviews(1) if dst.count > 0 else []

        elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()

        print(f"✅ COG CREATION: COG created - {output_size_mb:.1f} MB, {len(overviews)} overview levels", file=sys.stderr, flush=True)
        print(f"⏱️ COG CREATION: Processing time: {elapsed_time:.2f}s", file=sys.stderr, flush=True)

        # Upload to silver container OR save locally for testing
        container_name = params.get('container_name', 'unknown')

        if container_name == 'local':
            # LOCAL TESTING MODE: Save to output path instead of uploading
            import shutil
            final_output = output_blob_name
            shutil.copy(local_output, final_output)
            print(f"💾 COG CREATION: Saved locally to: {final_output}", file=sys.stderr, flush=True)
            silver_container = "local"

        else:
            # PRODUCTION MODE: Upload to Azure Blob Storage
            print(f"☁️ COG CREATION: Uploading to silver: {output_blob_name}", file=sys.stderr, flush=True)

            try:
                from infrastructure import BlobRepository
                blob_infra = BlobRepository()

                # Get silver container from config
                from config import get_config
                config_obj = get_config()
                silver_container = config_obj.silver_container_name

                # Upload
                with open(local_output, 'rb') as f:
                    blob_infra.upload_blob(
                        container_name=silver_container,
                        blob_name=output_blob_name,
                        data=f.read()
                    )

                print(f"✅ COG CREATION: Uploaded to silver container", file=sys.stderr, flush=True)

            except Exception as e:
                return {
                    "success": False,
                    "error": "UPLOAD_FAILED",
                    "message": f"Failed to upload COG to silver container: {e}"
                }

        # Success result
        return {
            "success": True,
            "result": {
                "cog_blob": output_blob_name,
                "cog_container": silver_container,
                "source_blob": params.get('blob_name', 'unknown'),
                "source_container": params.get('container_name', 'unknown'),
                "reprojection_performed": needs_reprojection,
                "source_crs": str(source_crs),
                "target_crs": str(target_crs),
                "bounds_4326": list(output_bounds) if output_crs == target_crs else None,
                "shape": list(output_shape),
                "size_mb": round(output_size_mb, 2),
                "compression": compression,
                "jpeg_quality": jpeg_quality if compression == "jpeg" else None,
                "tile_size": [512, 512],  # Default from rio-cogeo
                "overview_levels": overviews,
                "overview_resampling": overview_resampling,
                "reproject_resampling": reproject_resampling if needs_reprojection else None,
                "raster_type": raster_type,
                "processing_time_seconds": round(elapsed_time, 2)
            }
        }

    except Exception as e:
        import traceback
        print(f"❌ COG CREATION: Failed - {e}", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)

        return {
            "success": False,
            "error": "COG_CREATION_FAILED",
            "message": f"Failed to create COG: {e}",
            "exception": str(e),
            "traceback": traceback.format_exc()
        }

    finally:
        # Cleanup temp files
        try:
            if os.path.exists(local_output):
                os.remove(local_output)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
            print(f"🧹 COG CREATION: Cleaned up temp files", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"⚠️ COG CREATION: Failed to cleanup temp files: {e}", file=sys.stderr, flush=True)
