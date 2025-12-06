"""
Tiling Extraction Service - Stage 2 of Big Raster ETL.

Extracts tiles from large rasters following the tiling scheme from Stage 1.

Architectural Pattern:
    Stage 1: Generate tiling scheme (1 task)
    Stage 2: Sequential tile extraction via VSI + BytesIO (1 long task)
    Stage 3: Parallel COG conversion (N tasks)
    Stage 4: MosaicJSON + STAC metadata

VSI Architecture:
    - Zero /tmp disk usage: Reads via /vsicurl/ from Azure Blob
    - In-memory processing: BytesIO for tile buffers
    - Eliminates 500MB /tmp limit constraint
    - Job-scoped folders for intermediate tiles

Exports:
    extract_tiles: Main handler function
"""

import json
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Pydantic for band_names validation
from models.band_mapping import BandNames
from pydantic import ValidationError

# Logging
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "TilingExtraction")

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

    logger.info(f"📦 Extracting {total_tiles} tiles from raster...")

    with rasterio.open(raster_path) as src:
        logger.info(f"✅ Opened source raster: {src.width} × {src.height} pixels")
        logger.debug(f"   CRS: {src.crs}")

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
                logger.info(f"   [{i+1:3d}/{total_tiles:3d}] {tile_id:15s} [{progress*100:5.1f}% - ETA: {eta:5.1f}s]")

            # Call progress callback if provided
            if progress_callback:
                progress_callback(i + 1, total_tiles, tile_id, elapsed)

    total_duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(f"✅ Extraction complete: {total_tiles} tiles in {total_duration:.1f} seconds")

    return extracted_tiles


def extract_tiles(params: dict) -> dict:
    """
    Extract tiles from large raster - Stage 2 of Big Raster ETL.

    Uses GDAL VSI (/vsicurl/) to read raster directly from Azure Blob Storage,
    extracts tiles in-memory using BytesIO, uploads to blob storage.

    CRITICAL: This is a LONG-RUNNING task that extracts ALL tiles sequentially.
    - Sequential I/O is MUCH faster than parallel random access
    - Progress is reported via task metadata updates
    - Stage 3 will create N parallel tasks for COG conversion
    - ZERO /tmp disk usage (VSI + BytesIO eliminates 500MB limit)

    Args:
        params: Task parameters dict with:
            - container_name (str, REQUIRED): Bronze container name
            - blob_name (str, REQUIRED): Bronze blob name
            - tiling_scheme_blob (str, REQUIRED): Tiling scheme blob name (from Stage 1)
            - tiling_scheme_container (str, optional): Tiling scheme container (default: same as source)
            - output_container (str, optional): Output container (default: config.resolved_intermediate_tiles_container)
            - output_prefix (str, optional): Output blob prefix (default: "{job_id[:8]}/tiles/")
            - job_id (str, optional): Job ID for folder naming (uses first 8 chars as prefix)
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
    import rasterio
    from rasterio.windows import Window
    logger.debug("Extract tiles imports loaded")
    start_time = datetime.now(timezone.utc)

    try:
        # 🔍 CHECKPOINT 1: Handler Entry - Granular error handling for param extraction
        try:
            logger.info(f"🔍 [CHECKPOINT_START] extract_tiles handler entry for job_id: {params.get('job_id', 'unknown')[:16]}")
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT_START] FAILED - Cannot access params.get('job_id'): {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        try:
            logger.debug(f"🔍 [CHECKPOINT_PARAMS_TYPE] params type check: {type(params)}")
            logger.debug(f"   Parameters keys: {list(params.keys())}")
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT_PARAMS_TYPE] FAILED - params is not dict or missing keys(): {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # Extract parameters with granular error handling
        try:
            logger.debug(f"🔍 [CHECKPOINT_EXTRACT_PARAMS] Extracting all parameters...")
            container_name = params.get("container_name")
            blob_name = params.get("blob_name")
            tiling_scheme_blob = params.get("tiling_scheme_blob")
            tiling_scheme_container = params.get("tiling_scheme_container", container_name)
            job_id = params.get("job_id")
            task_id = params.get("task_id")
            repository = params.get("repository")

            # Validate band_names with Pydantic (strict validation, no fallbacks)
            band_names_raw = params.get("band_names")  # None if not provided
            if band_names_raw is not None:
                try:
                    band_names_model = BandNames(mapping=band_names_raw)
                    band_names = band_names_model.mapping  # dict[int, str] with int keys
                    logger.debug(f"✅ [CHECKPOINT_BAND_VALIDATION] band_names validated: {band_names}")
                except ValidationError as e:
                    error_msg = e.errors()[0]['msg'] if e.errors() else str(e)
                    error_str = f"Invalid band_names parameter: {error_msg}"
                    logger.error(f"❌ [CHECKPOINT_BAND_VALIDATION] {error_str}")
                    return {"success": False, "error": error_str}
            else:
                band_names = {}  # Empty dict = process all bands
                logger.debug(f"✅ [CHECKPOINT_BAND_VALIDATION] No band_names provided, will process all bands")

            logger.debug(f"✅ [CHECKPOINT_EXTRACT_PARAMS] All parameters extracted successfully")
            logger.debug(f"   container_name={container_name}")
            logger.debug(f"   blob_name={blob_name}")
            logger.debug(f"   tiling_scheme_blob={tiling_scheme_blob}")
            logger.debug(f"   band_names={band_names}")
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT_EXTRACT_PARAMS] FAILED during parameter extraction: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # Validate required parameters
        try:
            logger.debug(f"🔍 [CHECKPOINT_VALIDATE_PARAMS] Validating required parameters...")
            if not container_name or not blob_name or not tiling_scheme_blob:
                error_msg = f"Missing required parameters: container_name={container_name}, blob_name={blob_name}, tiling_scheme_blob={tiling_scheme_blob}"
                logger.error(f"❌ [CHECKPOINT_VALIDATE_PARAMS] {error_msg}")
                return {"success": False, "error": error_msg}
            logger.debug(f"✅ [CHECKPOINT_VALIDATE_PARAMS] All required parameters present")
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT_VALIDATE_PARAMS] FAILED during validation: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # 🔍 CHECKPOINT 2: Config Init
        try:
            logger.debug(f"🔍 [CHECKPOINT_CONFIG] Loading config...")
            from config import get_config
            config = get_config()
            logger.debug(f"✅ [CHECKPOINT_CONFIG] Config loaded successfully")
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT_CONFIG] FAILED: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # Resolve output container (default to intermediate tiles container from config)
        output_container = params.get("output_container", config.resolved_intermediate_tiles_container)

        # Generate default output prefix if not provided
        # Pattern: {job_id[:8]}/tiles/ (job-scoped folder for intermediate tiles)
        output_prefix = params.get("output_prefix")
        blob_stem = Path(blob_name).stem

        if not output_prefix:
            job_id_prefix = job_id[:8] if job_id else "unknown"
            output_prefix = f"{job_id_prefix}/tiles/"
            logger.info(f"📁 Using job-scoped folder: {output_prefix} (container: {output_container})")

        # 🔍 CHECKPOINT 3: BlobRepository Init
        try:
            logger.debug(f"🔍 [CHECKPOINT_BLOB_REPO] Initializing BlobRepository...")
            blob_repo = BlobRepository()
            logger.debug(f"✅ [CHECKPOINT_BLOB_REPO] BlobRepository initialized successfully")
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT_BLOB_REPO] FAILED: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # 🔍 CHECKPOINT 4: SAS URL Generation
        try:
            logger.info(f"🔍 [CHECKPOINT_SAS_URL] Generating SAS URL for VSI access: {blob_name}")
            sas_url = blob_repo.get_blob_url_with_sas(
                container_name=container_name,
                blob_name=blob_name,
                hours=4  # 4-hour buffer for long-running extraction (204 tiles ~3-4 min)
            )
            # Create VSI path for GDAL to access blob via HTTP
            vsi_raster_path = f"/vsicurl/{sas_url}"
            logger.info(f"✅ [CHECKPOINT_SAS_URL] VSI path created: /vsicurl/https://...")
            logger.debug(f"   Reading raster directly from Azure Blob Storage (no /tmp download)")
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT_SAS_URL] FAILED: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # 🔍 CHECKPOINT 5: Tiling Scheme Download
        try:
            logger.info(f"🔍 [CHECKPOINT_TILING_SCHEME] Downloading tiling scheme: {tiling_scheme_blob}")
            tiling_scheme_json = blob_repo.read_blob(tiling_scheme_container, tiling_scheme_blob)
            tiling_scheme = json.loads(tiling_scheme_json)
            logger.debug(f"✅ [CHECKPOINT_TILING_SCHEME] Tiling scheme loaded: {len(tiling_scheme.get('features', []))} tiles")
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT_TILING_SCHEME] FAILED: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # Extract tiles directly from VSI path and upload in-memory (no /tmp writes)
        logger.info(f"📦 Extracting and uploading tiles via VSI + BytesIO...")
        extraction_start = datetime.now(timezone.utc)
        tile_blobs = []
        tiles = tiling_scheme['features']
        total_tiles = len(tiles)

        # Import BytesIO for in-memory tile handling
        from io import BytesIO

        # 🔍 CHECKPOINT 6: VSI Raster Open (CRITICAL - likely failure point)
        try:
            logger.info(f"🔍 [CHECKPOINT_VSI_OPEN] Opening raster via VSI: {vsi_raster_path[:100]}...")
            logger.debug(f"   Blob: {blob_name}")
            logger.debug(f"   Container: {container_name}")

            src = rasterio.open(vsi_raster_path)

            logger.info(f"✅ [CHECKPOINT_VSI_OPEN] Raster opened successfully!")
            logger.debug(f"   Dimensions: {src.width}×{src.height} px")
            logger.debug(f"   Bands: {src.count}, Dtype: {src.dtypes[0]}")
            logger.debug(f"   CRS: {src.crs}")

            # Extract band indices from band_names dict
            # band_names format: {5: 'Red', 3: 'Green', 2: 'Blue'}
            if band_names and isinstance(band_names, dict) and len(band_names) > 0:
                # Get sorted band indices from dict keys
                band_indices = sorted([idx for idx in band_names.keys() if idx <= src.count])

                # Validate at least one band is valid
                if not band_indices:
                    logger.warning(f"⚠️  No valid bands in {band_names}, using first {min(3, src.count)} bands")
                    band_indices = list(range(1, min(4, src.count + 1)))
                    band_desc = "fallback RGB"
                else:
                    # Create readable description: "bands 2,3,5 (Blue, Green, Red)"
                    band_desc = ', '.join(f"{idx} ({band_names[idx]})" for idx in band_indices if idx in band_names)
            else:
                # No band selection specified, read all bands
                band_indices = list(range(1, src.count + 1))
                band_desc = "all bands"

            logger.info(f"🎯 [CHECKPOINT_BAND_MAPPING] Will read {len(band_indices)} of {src.count} bands: {band_desc}")
            logger.debug(f"   Band indices: {band_indices}")
            logger.debug(f"   Requested: {band_names}")
        except Exception as e:
            # VSI-specific error handling with detailed diagnostics
            error_str = str(e)
            error_msg = f"❌ [CHECKPOINT_VSI_OPEN] FAILED to open raster via VSI\n"
            error_msg += f"   Blob: {blob_name}\n"
            error_msg += f"   Container: {container_name}\n"
            error_msg += f"   VSI Path: {vsi_raster_path[:100]}...\n"
            error_msg += f"   Error: {error_str}\n"

            # Add helpful hints based on error type
            if "HTTP" in error_str or "404" in error_str or "403" in error_str:
                error_msg += "\n💡 HINT: VSI HTTP error - possible causes:\n"
                error_msg += "   - SAS URL expired or invalid\n"
                error_msg += "   - Blob does not exist in container\n"
                error_msg += "   - Network/firewall blocking HTTPS access\n"
            elif "timeout" in error_str.lower():
                error_msg += "\n💡 HINT: VSI timeout - possible causes:\n"
                error_msg += "   - Blob is too large for initial connection\n"
                error_msg += "   - Network latency issues\n"
                error_msg += "   - Azure Blob throttling\n"
            else:
                error_msg += "\n💡 HINT: Unexpected VSI error\n"

            error_msg += f"\n{traceback.format_exc()}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # 🔍 CHECKPOINT 7: Tile Extraction Loop
        with src:
            logger.info(f"✅ Opened source raster via VSI: {src.width} × {src.height} pixels")
            logger.debug(f"   CRS: {src.crs}")
            logger.info(f"🔍 [CHECKPOINT_TILE_LOOP] Starting tile extraction loop for {total_tiles} tiles...")

            for i, tile_feature in enumerate(tiles):
                try:
                    # 🔍 CHECKPOINT 7a: Tile Iteration Start
                    logger.debug(f"🔍 [CHECKPOINT_TILE_{i}] Starting tile {i+1}/{total_tiles}")

                    # Extract tile metadata
                    props = tile_feature['properties']
                    tile_id = props['tile_id']
                    pw = props['pixel_window']
                    logger.debug(f"   Tile ID: {tile_id}, Window: {pw['width']}x{pw['height']} @ ({pw['col_off']}, {pw['row_off']})")

                    # 🔍 CHECKPOINT 7b: VSI Read Operation
                    try:
                        logger.debug(f"🔍 [CHECKPOINT_TILE_{i}_READ] Reading tile data from VSI...")
                        logger.debug(f"   Reading bands: {band_indices}")
                        window = Window(
                            col_off=pw['col_off'],
                            row_off=pw['row_off'],
                            width=pw['width'],
                            height=pw['height']
                        )
                        # Read only the specified bands
                        tile_data = src.read(indexes=band_indices, window=window)
                        tile_transform = src.window_transform(window)

                        # Calculate tile size in MB for logging
                        tile_size_mb = tile_data.nbytes / (1024 * 1024)
                        logger.debug(f"✅ [CHECKPOINT_TILE_{i}_READ] Tile data read successfully: {tile_data.shape} ({tile_size_mb:.2f} MB)")
                    except Exception as e:
                        error_msg = f"❌ [CHECKPOINT_TILE_{i}_READ] FAILED to read tile from VSI: {str(e)}"
                        logger.error(error_msg)
                        logger.error(traceback.format_exc())
                        raise

                    # 🔍 CHECKPOINT 7c: BytesIO Write Operation
                    try:
                        logger.debug(f"🔍 [CHECKPOINT_TILE_{i}_WRITE] Writing tile to BytesIO buffer...")
                        tile_buffer = BytesIO()
                        profile = src.profile.copy()
                        profile.update({
                            'width': pw['width'],
                            'height': pw['height'],
                            'transform': tile_transform,
                            'count': len(band_indices)  # Update band count to match extracted bands
                        })

                        with rasterio.open(tile_buffer, 'w', **profile) as dst:
                            dst.write(tile_data)

                        logger.debug(f"✅ [CHECKPOINT_TILE_{i}_WRITE] Tile written to buffer: {tile_buffer.tell()} bytes")
                    except Exception as e:
                        error_msg = f"❌ [CHECKPOINT_TILE_{i}_WRITE] FAILED to write tile to BytesIO: {str(e)}"
                        logger.error(error_msg)
                        logger.error(traceback.format_exc())
                        raise

                    # 🔍 CHECKPOINT 7d: Blob Upload Operation
                    try:
                        tile_buffer.seek(0)  # Reset buffer position for reading
                        # Pattern: {job_id[:8]}/tiles/{blob_stem}_tile_0_0.tif
                        blob_name_full = f"{output_prefix}{blob_stem}_{tile_id}.tif"

                        logger.debug(f"🔍 [CHECKPOINT_TILE_{i}_UPLOAD] Uploading to blob: {blob_name_full}...")
                        blob_repo.write_blob(
                            container=output_container,
                            blob_path=blob_name_full,
                            data=tile_buffer,
                            overwrite=True,
                            content_type="image/tiff"
                        )
                        logger.debug(f"✅ [CHECKPOINT_TILE_{i}_UPLOAD] Blob uploaded successfully")
                    except Exception as e:
                        error_msg = f"❌ [CHECKPOINT_TILE_{i}_UPLOAD] FAILED to upload blob: {str(e)}"
                        logger.error(error_msg)
                        logger.error(traceback.format_exc())
                        raise

                    tile_blobs.append(blob_name_full)

                    # Progress reporting
                    elapsed = (datetime.now(timezone.utc) - extraction_start).total_seconds()
                    progress = (i + 1) / total_tiles
                    eta = (elapsed / progress) - elapsed if progress > 0 else 0

                    # Log every 10 tiles or at completion
                    if (i + 1) % 10 == 0 or (i + 1) == total_tiles:
                        logger.info(f"   [{i+1:3d}/{total_tiles:3d}] {tile_id:15s} [{progress*100:5.1f}% - ETA: {eta:5.1f}s]")

                    # Update task metadata with progress (if provided)
                    if repository and task_id:
                        progress_metadata = {
                            "extraction_progress": {
                                "tiles_extracted": i + 1,
                                "total_tiles": total_tiles,
                                "current_tile": tile_id,
                                "elapsed_seconds": round(elapsed, 2),
                                "percent_complete": round(progress * 100, 2)
                            }
                        }
                        try:
                            repository.update_task_metadata(task_id, progress_metadata, merge=True)
                        except Exception as e:
                            logger.warning(f"⚠️  Failed to update metadata: {e}")

                except Exception as e:
                    # Catch-all for any tile processing failure
                    error_msg = f"❌ [CHECKPOINT_TILE_{i}_FAILED] Tile {i+1}/{total_tiles} (ID: {tile_id if 'tile_id' in locals() else 'unknown'}) processing failed"
                    logger.error(error_msg)
                    logger.error(f"   Error: {str(e)}")
                    logger.error(traceback.format_exc())

                    return {
                        "success": False,
                        "error": error_msg,
                        "error_details": str(e),
                        "tiles_completed": i,
                        "total_tiles": total_tiles
                    }

        # Calculate total processing time
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        extraction_time = (datetime.now(timezone.utc) - extraction_start).total_seconds()

        logger.info(f"✅ Tile extraction complete!")
        logger.info(f"   Extracted + Uploaded: {len(tile_blobs)} tiles in {extraction_time:.1f}s")
        logger.info(f"   Total: {processing_time:.1f}s")
        logger.debug(f"   💾 /tmp disk usage: ~0MB (VSI + BytesIO in-memory processing)")

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
                "upload_time_seconds": round(extraction_time, 2),  # Combined now
                "processing_time_seconds": round(processing_time, 2)
            }
        }

    except Exception as e:
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        error_msg = f"Failed to extract tiles: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"❌ ERROR: {error_msg}")

        return {
            "success": False,
            "error": error_msg,
            "processing_time_seconds": round(processing_time, 2)
        }
