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
            - blob_url (str, REQUIRED): Azure blob URL for bronze raster (with SAS token)
            - source_crs (str, REQUIRED): CRS from validation stage
            - target_crs (str, optional): Target CRS (default: EPSG:4326)
            - raster_type (dict, REQUIRED): Full raster_type dict from validation stage
                Structure: {"detected_type": str, "optimal_cog_settings": {...}}
            - output_blob_name (str, REQUIRED): Silver container blob path
            - container_name (str): Bronze container name
            - blob_name (str): Bronze blob name
            - output_tier (str, optional): COG tier (visualization, analysis, archive) - default: analysis
            - compression (str, optional): User override for compression (DEPRECATED - use output_tier)
            - jpeg_quality (int, optional): JPEG quality (1-100)
            - overview_resampling (str, optional): User override
            - reproject_resampling (str, optional): User override

    Returns:
        dict: {
            "success": bool,
            "result": {
                "cog_blob": str,           # ← Output COG path in silver container
                "cog_container": str,      # ← Silver container name
                "cog_tier": str,           # ← COG tier (visualization/analysis/archive)
                "storage_tier": str,       # ← Azure storage tier (hot/cool/archive)
                "source_blob": str,
                "source_container": str,
                "reprojection_performed": bool,
                "source_crs": str,
                "target_crs": str,
                "bounds_4326": list,       # ← [minx, miny, maxx, maxy]
                "shape": list,             # ← [height, width]
                "size_mb": float,
                "compression": str,
                "jpeg_quality": int,
                "tile_size": list,
                "overview_levels": list,
                "overview_resampling": str,
                "reproject_resampling": str,
                "raster_type": str,
                "processing_time_seconds": float,
                "tier_profile": {...}
            },
            "error": str (if success=False),
            "message": str (if success=False),
            "traceback": str (if success=False)
        }

    NOTE: Downstream consumers (Stage 3+) rely on result["cog_blob"] field.
    """
    import traceback

    # STEP 0: Initialize logger
    logger = None
    try:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "create_cog")
        logger.info("✅ STEP 0: Logger initialized successfully")
    except Exception as e:
        return {
            "success": False,
            "error": "LOGGER_INIT_FAILED",
            "message": f"Failed to initialize logger: {e}",
            "traceback": traceback.format_exc()
        }

    # STEP 1: Extract and validate parameters
    try:
        logger.info("🔄 STEP 1: Extracting and validating parameters...")

        blob_url = params.get('blob_url')
        source_crs = params.get('source_crs')
        target_crs = params.get('target_crs', 'EPSG:4326')
        raster_type = params.get('raster_type', {}).get('detected_type', 'unknown')
        optimal_settings = params.get('raster_type', {}).get('optimal_cog_settings', {})

        # Get COG tier configuration from config
        from config import get_config, CogTier, COG_TIER_PROFILES
        config_obj = get_config()

        # Get output_tier parameter (default to analysis)
        output_tier_str = params.get('output_tier', 'analysis')
        try:
            output_tier = CogTier(output_tier_str)
        except ValueError:
            logger.warning(f"⚠️ Invalid output_tier '{output_tier_str}', defaulting to 'analysis'")
            output_tier = CogTier.ANALYSIS

        # Get tier profile
        tier_profile = COG_TIER_PROFILES[output_tier]
        logger.info(f"   Using tier profile: {output_tier.value}")
        logger.info(f"   Profile: compression={tier_profile.compression}, storage_tier={tier_profile.storage_tier.value}")

        # Check tier compatibility with raster type
        raster_metadata = params.get('raster_type', {})
        band_count = raster_metadata.get('band_count', 3)
        data_type = raster_metadata.get('data_type', 'uint8')

        if not tier_profile.is_compatible(band_count, data_type):
            logger.warning(f"⚠️ Tier '{output_tier.value}' not compatible with {band_count} bands, {data_type}")
            logger.warning(f"   Falling back to 'analysis' tier (DEFLATE - universal)")
            output_tier = CogTier.ANALYSIS
            tier_profile = COG_TIER_PROFILES[output_tier]

        # Use tier profile settings (allow user overrides)
        compression = params.get('compression') or tier_profile.compression.lower()
        jpeg_quality = params.get('jpeg_quality') or tier_profile.quality or 85
        overview_resampling = params.get('overview_resampling') or optimal_settings.get('overview_resampling', 'cubic')
        reproject_resampling = params.get('reproject_resampling') or optimal_settings.get('reproject_resampling', 'cubic')

        output_blob_name = params.get('output_blob_name')
        container_name = params.get('container_name', 'unknown')
        blob_name = params.get('blob_name', 'unknown')

        # Add tier suffix to output blob name
        # Example: sample.tif → sample_analysis.tif
        if output_blob_name and not any(tier.value in output_blob_name for tier in CogTier):
            base_name = output_blob_name.rsplit('.', 1)[0] if '.' in output_blob_name else output_blob_name
            extension = output_blob_name.rsplit('.', 1)[1] if '.' in output_blob_name else 'tif'
            output_blob_name = f"{base_name}_{output_tier.value}.{extension}"
            logger.info(f"   Added tier suffix to output: {output_blob_name}")

        if not all([blob_url, source_crs, output_blob_name]):
            missing = []
            if not blob_url: missing.append('blob_url')
            if not source_crs: missing.append('source_crs')
            if not output_blob_name: missing.append('output_blob_name')

            logger.error(f"❌ STEP 1 FAILED: Missing required parameters: {', '.join(missing)}")
            return {
                "success": False,
                "error": "PARAMETER_ERROR",
                "message": f"Missing required parameters: {', '.join(missing)}"
            }

        logger.info(f"✅ STEP 1: Parameters validated - blob={blob_name}, container={container_name}")
        logger.info(f"   Type: {raster_type}, Tier: {output_tier.value}, Compression: {compression}, CRS: {source_crs} → {target_crs}")

    except Exception as e:
        logger.error(f"❌ STEP 1 FAILED: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "PARAMETER_ERROR",
            "message": f"Failed to extract parameters: {e}",
            "traceback": traceback.format_exc()
        }

    # STEP 2: Lazy import dependencies
    try:
        logger.info("🔄 STEP 2: Lazy importing rasterio and rio-cogeo dependencies...")
        rasterio, Resampling, cog_translate, cog_profiles = _lazy_imports()
        logger.info("✅ STEP 2: Dependencies imported successfully (rasterio, rio-cogeo)")
    except ImportError as e:
        logger.error(f"❌ STEP 2 FAILED: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "DEPENDENCY_LOAD_FAILED",
            "message": f"Failed to import rio-cogeo dependencies: {e}",
            "traceback": traceback.format_exc()
        }

    # STEP 2b: Import blob storage
    try:
        logger.info("🔄 STEP 2b: Importing BlobRepository...")
        from infrastructure.blob import BlobRepository
        logger.info("✅ STEP 2b: BlobRepository imported successfully")
    except ImportError as e:
        logger.error(f"❌ STEP 2b FAILED: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "DEPENDENCY_LOAD_FAILED",
            "message": f"Failed to import BlobRepository: {e}",
            "traceback": traceback.format_exc()
        }

    # STEP 3: Setup COG profile and configuration
    temp_dir = None
    local_output = None

    # Wrap entire COG creation in try-finally for cleanup
    try:
        # STEP 3: Setup COG profile and configuration
        logger.info("🔄 STEP 3: Setting up COG profile and temp directory...")

        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="cog_")
        local_output = os.path.join(temp_dir, "output_cog.tif")
        logger.info(f"   Created temp directory: {temp_dir}")

        start_time = datetime.now(timezone.utc)

        # Get COG profile for compression type
        try:
            cog_profile = cog_profiles.get(compression)
            logger.info(f"   Using COG profile: {compression}")
        except KeyError:
            logger.warning(f"⚠️ Unknown compression '{compression}', falling back to deflate")
            cog_profile = cog_profiles.get('deflate')

        # Add JPEG quality if using JPEG compression
        if compression == "jpeg":
            cog_profile["QUALITY"] = jpeg_quality
            logger.info(f"   JPEG quality: {jpeg_quality}")

        # Get resampling enum for overviews
        try:
            overview_resampling_enum = getattr(Resampling, overview_resampling)
        except AttributeError:
            logger.warning(f"⚠️ Unknown resampling '{overview_resampling}', using cubic")
            overview_resampling_enum = Resampling.cubic

        # Get in_memory setting from config
        from config import get_config
        config_obj = get_config()
        in_memory = config_obj.raster_cog_in_memory

        logger.info(f"✅ STEP 3: COG profile configured")
        logger.info(f"   Processing mode: {'in-memory (RAM)' if in_memory else 'disk-based (/tmp SSD)'}")

        # STEP 4: Determine reprojection needs
        logger.info("🔄 STEP 4: Checking CRS and reprojection requirements...")

        needs_reprojection = (str(source_crs) != str(target_crs))

        # Configure reprojection if needed
        if needs_reprojection:
            logger.info(f"   Reprojection needed: {source_crs} → {target_crs}")
            config = {
                "dst_crs": target_crs,
                "resampling": getattr(Resampling, reproject_resampling),
            }
            logger.info(f"   Reprojection resampling: {reproject_resampling}")
        else:
            logger.info(f"   No reprojection needed (already {target_crs})")
            config = {}

        logger.info(f"✅ STEP 4: CRS check complete")

        # STEP 5: Create COG (with optional reprojection in single pass)
        logger.info("🔄 STEP 5: Creating COG with cog_translate()...")
        logger.info(f"   Input: {blob_url}")
        logger.info(f"   Output: {local_output}")
        logger.info(f"   Compression: {compression}, Overview resampling: {overview_resampling}")

        # rio-cogeo expects string name, not enum object
        overview_resampling_name = overview_resampling_enum.name if hasattr(overview_resampling_enum, 'name') else overview_resampling
        logger.info(f"   Overview resampling (for cog_translate): {overview_resampling_name}")

        cog_translate(
            blob_url,
            local_output,
            cog_profile,
            config=config,
            overview_level=None,  # Auto-calculate optimal levels
            overview_resampling=overview_resampling_name,  # Use string name, not enum
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

        logger.info(f"✅ STEP 5: COG created successfully")
        logger.info(f"   Size: {output_size_mb:.1f} MB, Overview levels: {len(overviews)}")
        logger.info(f"   Processing time: {elapsed_time:.2f}s")

        # STEP 6: Upload to silver container OR save locally for testing
        logger.info("🔄 STEP 6: Uploading COG to silver container...")

        if container_name == 'local':
            # LOCAL TESTING MODE: Save to output path instead of uploading
            logger.info("   LOCAL TESTING MODE: Saving to local filesystem...")
            import shutil
            final_output = output_blob_name
            shutil.copy(local_output, final_output)
            logger.info(f"   Saved locally to: {final_output}")
            silver_container = "local"

        else:
            # PRODUCTION MODE: Upload to Azure Blob Storage
            logger.info(f"   PRODUCTION MODE: Uploading to Azure blob storage...")

            from infrastructure import BlobRepository
            blob_infra = BlobRepository()

            # Get silver container from config
            from config import get_config
            config_obj = get_config()
            silver_container = config_obj.silver_container_name

            logger.info(f"   Target container: {silver_container}")
            logger.info(f"   Target blob: {output_blob_name}")

            # Upload
            with open(local_output, 'rb') as f:
                blob_infra.write_blob(
                    container=silver_container,
                    blob_path=output_blob_name,
                    data=f.read()
                )

            logger.info(f"✅ STEP 6: COG uploaded successfully to {silver_container}/{output_blob_name}")

        # Success result
        logger.info("🎉 COG creation pipeline completed successfully")
        return {
            "success": True,
            "result": {
                "cog_blob": output_blob_name,
                "cog_container": silver_container,
                "cog_tier": output_tier.value,
                "storage_tier": tier_profile.storage_tier.value,
                "source_blob": blob_name,
                "source_container": container_name,
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
                "processing_time_seconds": round(elapsed_time, 2),
                "tier_profile": {
                    "tier": output_tier.value,
                    "compression": tier_profile.compression,
                    "storage_tier": tier_profile.storage_tier.value,
                    "use_case": tier_profile.use_case,
                    "description": tier_profile.description
                }
            }
        }

    except Exception as e:
        # Catch all errors from STEPs 3-6
        logger.error(f"❌ COG CREATION FAILED: {e}\n{traceback.format_exc()}")

        # Determine which step failed based on what variables are defined
        if 'cog_profile' not in locals():
            error_code = "SETUP_FAILED"
            step_info = "STEP 3 (setup)"
        elif 'config' not in locals():
            error_code = "CRS_CHECK_FAILED"
            step_info = "STEP 4 (CRS check)"
        elif 'output_size_mb' not in locals():
            error_code = "COG_TRANSLATE_FAILED"
            step_info = "STEP 5 (cog_translate)"
        elif 'silver_container' not in locals():
            error_code = "UPLOAD_FAILED"
            step_info = "STEP 6 (upload)"
        else:
            error_code = "COG_CREATION_FAILED"
            step_info = "Unknown step"

        return {
            "success": False,
            "error": error_code,
            "message": f"{step_info} failed: {e}",
            "traceback": traceback.format_exc()
        }

    finally:
        # STEP 7: Cleanup temp files (non-critical)
        if logger and temp_dir and local_output:
            try:
                logger.info("🔄 STEP 7: Cleaning up temporary files...")
                if os.path.exists(local_output):
                    os.remove(local_output)
                    logger.info(f"   Removed: {local_output}")
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
                    logger.info(f"   Removed: {temp_dir}")
                logger.info("✅ STEP 7: Cleanup complete")
            except Exception as e:
                logger.warning(f"⚠️ STEP 7: Cleanup warning (non-critical): {e}")
                # Don't fail the entire operation due to cleanup issues
