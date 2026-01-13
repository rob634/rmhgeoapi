# ============================================================================
# PROCESS LARGE RASTER COMPLETE HANDLER (Docker)
# ============================================================================
# STATUS: Services - Consolidated large raster handler for Docker worker
# PURPOSE: Single handler that does tiling → extraction → COG → MosaicJSON → STAC
# CREATED: 13 JAN 2026 - F7.18 Docker Large Raster Pipeline
# ============================================================================
"""
Process Large Raster Complete - Consolidated Docker Handler.

Combines all five stages of large raster processing into a single handler:
    Phase 1: Generate tiling scheme
    Phase 2: Extract tiles (sequential)
    Phase 3: Create COGs for each tile (sequential)
    Phase 4: Create MosaicJSON
    Phase 5: Create STAC collection

Why Consolidated:
    - Docker has no timeout (unlike 10-min Function App limit)
    - Eliminates stage progression overhead
    - Single atomic operation with checkpoint/resume
    - Verbose progress logging for monitoring

Progress Tracking:
    - Task metadata updated after each phase and sub-operation
    - Enables real-time progress monitoring via task status endpoint
    - Similar UX to multi-stage Function App job

Checkpoint/Resume Support:
    - Each phase saved to checkpoint
    - On crash/restart, resumes from last completed phase
    - Artifact validation ensures outputs exist before checkpoint

Exports:
    process_large_raster_complete: Consolidated handler function
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def process_large_raster_complete(params: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Complete large raster processing in single execution.

    Consolidates tiling → extraction → COG → MosaicJSON → STAC into one handler.
    Designed for Docker worker with no timeout constraints.

    Args:
        params: Task parameters with:
            - _task_id: Task ID for checkpoint/progress tracking
            - _job_id: Job ID for folder naming
            - blob_url: Azure blob URL with SAS token
            - blob_name: Source blob path
            - container_name: Source container
            - target_crs: Target CRS for reprojection
            - tile_size: Tile size (None = auto-calculate)
            - overlap: Tile overlap in pixels (default 512)
            - band_names: Optional band mapping
            - output_tier: COG tier ('analysis', 'visualization', 'archive')
            - collection_id: STAC collection
        context: Optional context (not used in Docker mode)

    Returns:
        dict: Combined result with all phase results
    """
    start_time = time.time()

    blob_name = params.get('blob_name', 'unknown')
    container_name = params.get('container_name', 'unknown')
    task_id = params.get('_task_id')
    job_id = params.get('_job_id', 'unknown')

    logger.info("=" * 70)
    logger.info("PROCESS LARGE RASTER COMPLETE - Docker Handler (F7.18)")
    logger.info(f"Source: {container_name}/{blob_name}")
    logger.info(f"Job ID: {job_id[:16]}...")
    if task_id:
        logger.info(f"Task ID: {task_id[:16]}... (checkpoint/progress enabled)")
    logger.info("=" * 70)

    # Initialize checkpoint manager and progress tracker
    checkpoint = None
    task_repo = None
    if task_id:
        try:
            from infrastructure import CheckpointManager
            from infrastructure.factory import RepositoryFactory
            task_repo = RepositoryFactory.create_task_repository()
            checkpoint = CheckpointManager(task_id, task_repo)
            if checkpoint.current_phase > 0:
                logger.info(f"🔄 RESUMING from phase {checkpoint.current_phase}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize CheckpointManager: {e}")

    # Progress update helper
    def update_progress(phase: int, phase_name: str, detail: str, percent: float = None, extra: Dict = None):
        """Update task metadata with progress info."""
        if task_repo and task_id:
            try:
                progress = {
                    "current_phase": phase,
                    "phase_name": phase_name,
                    "detail": detail,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": round(time.time() - start_time, 1),
                }
                if percent is not None:
                    progress["percent_complete"] = round(percent, 1)
                if extra:
                    progress.update(extra)
                task_repo.update_task_metadata(task_id, {"progress": progress}, merge=True)
                logger.info(f"📊 Progress: Phase {phase} ({phase_name}) - {detail}" +
                           (f" [{percent:.1f}%]" if percent else ""))
            except Exception as e:
                logger.debug(f"Progress update failed (non-fatal): {e}")

    # Track results from each phase
    tiling_result = {}
    extraction_result = {}
    cog_results = []
    mosaicjson_result = {}
    stac_result = {}

    # Load config
    from config import get_config
    config = get_config()

    try:
        # =====================================================================
        # PHASE 1: GENERATE TILING SCHEME
        # =====================================================================
        if checkpoint and checkpoint.should_skip(1):
            logger.info("⏭️ PHASE 1: Skipping tiling scheme (checkpoint)")
            tiling_result = checkpoint.get_data('tiling_result', {})
        else:
            update_progress(1, "tiling_scheme", "Generating tiling scheme...", 0)
            logger.info("🔄 PHASE 1: Generating tiling scheme...")
            phase1_start = time.time()

            from .tiling_scheme import generate_tiling_scheme

            tiling_params = {
                'container_name': container_name,
                'blob_name': blob_name,
                'tile_size': params.get('tile_size'),
                'overlap': params.get('overlap', 512),
                'output_container': config.storage.silver.cogs,
                'band_names': params.get('band_names'),
                'target_crs': params.get('target_crs') or config.raster.target_crs,
            }

            tiling_response = generate_tiling_scheme(tiling_params)

            if not tiling_response.get('success'):
                logger.error(f"❌ Tiling scheme generation failed: {tiling_response.get('error')}")
                return {
                    "success": False,
                    "error": "TILING_SCHEME_FAILED",
                    "message": tiling_response.get('message', 'Tiling scheme generation failed'),
                    "phase": 1,
                    "phase_name": "tiling_scheme",
                }

            tiling_result = tiling_response.get('result', {})
            phase1_duration = time.time() - phase1_start

            logger.info(f"✅ PHASE 1 complete: {phase1_duration:.2f}s")
            logger.info(f"   Tile count: {tiling_result.get('tile_count')}")
            logger.info(f"   Grid: {tiling_result.get('grid_dimensions')}")
            logger.info(f"   Tile size: {tiling_result.get('tile_size_used')}px")

            update_progress(1, "tiling_scheme", "Complete", 10, {
                "tile_count": tiling_result.get('tile_count'),
                "grid_dimensions": tiling_result.get('grid_dimensions'),
                "duration_seconds": round(phase1_duration, 1)
            })

            if checkpoint:
                checkpoint.save(phase=1, data={'tiling_result': tiling_result})

        # =====================================================================
        # PHASE 2: EXTRACT TILES
        # =====================================================================
        if checkpoint and checkpoint.should_skip(2):
            logger.info("⏭️ PHASE 2: Skipping tile extraction (checkpoint)")
            extraction_result = checkpoint.get_data('extraction_result', {})
        else:
            tile_count = tiling_result.get('tile_count', 0)
            update_progress(2, "extract_tiles", f"Extracting {tile_count} tiles...", 10)
            logger.info(f"🔄 PHASE 2: Extracting {tile_count} tiles...")
            phase2_start = time.time()

            from .tiling_extraction import extract_tiles

            extraction_params = {
                'container_name': container_name,
                'blob_name': blob_name,
                'tiling_scheme_blob': tiling_result.get('tiling_scheme_blob'),
                'tiling_scheme_container': config.storage.silver.cogs,
                'output_container': config.resolved_intermediate_tiles_container,
                'job_id': job_id,
                'band_names': params.get('band_names') or tiling_result.get('raster_metadata', {}).get('used_band_names'),
                # Progress callback for per-tile updates
                '_progress_callback': lambda idx, total: update_progress(
                    2, "extract_tiles",
                    f"Extracting tile {idx+1}/{total}",
                    10 + (idx / total) * 20,
                    {"tiles_extracted": idx + 1, "total_tiles": total}
                ) if task_repo else None,
            }

            extraction_response = extract_tiles(extraction_params)

            if not extraction_response.get('success'):
                logger.error(f"❌ Tile extraction failed: {extraction_response.get('error')}")
                return {
                    "success": False,
                    "error": "TILE_EXTRACTION_FAILED",
                    "message": extraction_response.get('message', 'Tile extraction failed'),
                    "phase": 2,
                    "phase_name": "extract_tiles",
                    "tiling": tiling_result,
                }

            extraction_result = extraction_response.get('result', {})
            phase2_duration = time.time() - phase2_start

            logger.info(f"✅ PHASE 2 complete: {phase2_duration:.2f}s")
            logger.info(f"   Tiles extracted: {extraction_result.get('tile_count')}")

            update_progress(2, "extract_tiles", "Complete", 30, {
                "tiles_extracted": extraction_result.get('tile_count'),
                "duration_seconds": round(phase2_duration, 1)
            })

            if checkpoint:
                checkpoint.save(phase=2, data={'extraction_result': extraction_result})

        # =====================================================================
        # PHASE 3: CREATE COGS
        # =====================================================================
        if checkpoint and checkpoint.should_skip(3):
            logger.info("⏭️ PHASE 3: Skipping COG creation (checkpoint)")
            cog_results = checkpoint.get_data('cog_results', [])
        else:
            tile_blobs = extraction_result.get('tile_blobs', [])
            tile_count = len(tile_blobs)
            source_crs = extraction_result.get('source_crs')
            raster_metadata = extraction_result.get('raster_metadata', {})

            update_progress(3, "create_cogs", f"Creating {tile_count} COGs...", 30)
            logger.info(f"🔄 PHASE 3: Creating {tile_count} COGs...")
            phase3_start = time.time()

            from .raster_cog import create_cog

            # Build raster_type dict from metadata
            raster_type = {
                "detected_type": raster_metadata.get("detected_type", "unknown"),
                "band_count": raster_metadata.get("band_count", 3),
                "data_type": raster_metadata.get("data_type", "uint8"),
                "optimal_cog_settings": {}
            }

            blob_stem = Path(blob_name).stem
            output_folder = params.get('output_folder')
            target_crs = params.get('target_crs') or config.raster.target_crs
            jpeg_quality = params.get('jpeg_quality') or config.raster.cog_jpeg_quality

            cog_results = []
            cog_blobs = []

            for idx, tile_blob in enumerate(tile_blobs):
                # Progress update
                percent = 30 + (idx / tile_count) * 40
                update_progress(3, "create_cogs", f"COG {idx+1}/{tile_count}", percent, {
                    "cogs_created": idx,
                    "total_cogs": tile_count
                })
                logger.info(f"   📦 COG {idx+1}/{tile_count}: {tile_blob.split('/')[-1]}")

                # Generate output filename
                tile_filename = tile_blob.split('/')[-1]
                output_filename = tile_filename.replace('.tif', '_cog.tif')
                if output_folder:
                    output_blob_name = f"{output_folder}/{output_filename}"
                else:
                    output_blob_name = output_filename

                cog_params = {
                    'container_name': config.resolved_intermediate_tiles_container,
                    'blob_name': tile_blob,
                    'source_crs': source_crs,
                    'target_crs': target_crs,
                    'raster_type': raster_type,
                    'output_tier': params.get('output_tier', 'analysis'),
                    'output_blob_name': output_blob_name,
                    'output_container': config.storage.silver.cogs,
                    'jpeg_quality': jpeg_quality,
                    'overview_resampling': config.raster.overview_resampling,
                    'reproject_resampling': config.raster.reproject_resampling,
                    'in_memory': False,  # Docker uses disk for large files
                }

                cog_response = create_cog(cog_params)

                if not cog_response.get('success'):
                    logger.error(f"❌ COG creation failed for tile {idx+1}: {cog_response.get('error')}")
                    return {
                        "success": False,
                        "error": "COG_CREATION_FAILED",
                        "message": f"COG creation failed for tile {idx+1}: {cog_response.get('error')}",
                        "phase": 3,
                        "phase_name": "create_cogs",
                        "tile_index": idx,
                        "tiling": tiling_result,
                        "extraction": extraction_result,
                    }

                cog_result = cog_response.get('result', {})
                cog_results.append(cog_result)
                cog_blob = cog_result.get('output_blob') or cog_result.get('cog_blob')
                if cog_blob:
                    cog_blobs.append(cog_blob)

            phase3_duration = time.time() - phase3_start

            logger.info(f"✅ PHASE 3 complete: {phase3_duration:.2f}s")
            logger.info(f"   COGs created: {len(cog_blobs)}")

            update_progress(3, "create_cogs", "Complete", 70, {
                "cogs_created": len(cog_blobs),
                "duration_seconds": round(phase3_duration, 1)
            })

            if checkpoint:
                checkpoint.save(phase=3, data={
                    'cog_results': cog_results,
                    'cog_blobs': cog_blobs,
                })

        # Get cog_blobs from results if resuming
        if not cog_results:
            cog_blobs = checkpoint.get_data('cog_blobs', []) if checkpoint else []
        else:
            cog_blobs = [r.get('output_blob') or r.get('cog_blob') for r in cog_results if r]

        # =====================================================================
        # PHASE 4: CREATE MOSAICJSON
        # =====================================================================
        if checkpoint and checkpoint.should_skip(4):
            logger.info("⏭️ PHASE 4: Skipping MosaicJSON (checkpoint)")
            mosaicjson_result = checkpoint.get_data('mosaicjson_result', {})
        else:
            update_progress(4, "create_mosaicjson", f"Creating MosaicJSON from {len(cog_blobs)} COGs...", 70)
            logger.info(f"🔄 PHASE 4: Creating MosaicJSON from {len(cog_blobs)} COGs...")
            phase4_start = time.time()

            from .raster_mosaicjson import create_mosaicjson

            # Generate MosaicJSON output path
            blob_stem = Path(blob_name).stem
            mosaicjson_blob = f"{blob_stem}_mosaic.json"
            if params.get('output_folder'):
                mosaicjson_blob = f"{params['output_folder']}/{mosaicjson_blob}"

            mosaicjson_params = {
                'cog_blobs': cog_blobs,
                'cog_container': config.storage.silver.cogs,
                'output_blob': mosaicjson_blob,
                'output_container': config.storage.silver.cogs,
                'name': blob_stem,
                'description': f"MosaicJSON for {blob_name}",
            }

            mosaicjson_response = create_mosaicjson(mosaicjson_params)

            if not mosaicjson_response.get('success'):
                logger.warning(f"⚠️ MosaicJSON creation failed (non-fatal): {mosaicjson_response.get('error')}")
                mosaicjson_result = {
                    "degraded": True,
                    "error": mosaicjson_response.get('error'),
                }
            else:
                mosaicjson_result = mosaicjson_response.get('result', {})

            phase4_duration = time.time() - phase4_start

            logger.info(f"✅ PHASE 4 complete: {phase4_duration:.2f}s")
            if mosaicjson_result.get('mosaicjson_blob'):
                logger.info(f"   MosaicJSON: {mosaicjson_result.get('mosaicjson_blob')}")

            update_progress(4, "create_mosaicjson", "Complete", 85, {
                "mosaicjson_blob": mosaicjson_result.get('mosaicjson_blob'),
                "duration_seconds": round(phase4_duration, 1)
            })

            if checkpoint:
                checkpoint.save(phase=4, data={'mosaicjson_result': mosaicjson_result})

        # =====================================================================
        # PHASE 5: CREATE STAC COLLECTION
        # =====================================================================
        if checkpoint and checkpoint.should_skip(5):
            logger.info("⏭️ PHASE 5: Skipping STAC (checkpoint)")
            stac_result = checkpoint.get_data('stac_result', {})
        else:
            update_progress(5, "create_stac", "Creating STAC collection...", 85)
            logger.info("🔄 PHASE 5: Creating STAC collection...")
            phase5_start = time.time()

            from .raster_stac_collection import create_stac_collection

            collection_id = params.get('collection_id') or config.raster.stac_default_collection
            blob_stem = Path(blob_name).stem

            stac_params = {
                'collection_id': collection_id,
                'item_id': params.get('item_id') or blob_stem,
                'cog_blobs': cog_blobs,
                'cog_container': config.storage.silver.cogs,
                'mosaicjson_blob': mosaicjson_result.get('mosaicjson_blob'),
                'mosaicjson_container': config.storage.silver.cogs,
                'title': f"Large Raster: {blob_stem}",
                'description': f"Tiled COG mosaic from {blob_name}",
                # Platform passthrough
                'dataset_id': params.get('dataset_id'),
                'resource_id': params.get('resource_id'),
                'version_id': params.get('version_id'),
                'access_level': params.get('access_level'),
            }

            stac_response = create_stac_collection(stac_params)

            if not stac_response.get('success'):
                logger.warning(f"⚠️ STAC creation failed (non-fatal): {stac_response.get('error')}")
                stac_result = {
                    "degraded": True,
                    "error": stac_response.get('error'),
                }
            else:
                stac_result = stac_response.get('result', {})

            phase5_duration = time.time() - phase5_start

            logger.info(f"✅ PHASE 5 complete: {phase5_duration:.2f}s")
            if stac_result.get('collection_id'):
                logger.info(f"   Collection: {stac_result.get('collection_id')}")

            update_progress(5, "create_stac", "Complete", 100, {
                "collection_id": stac_result.get('collection_id'),
                "duration_seconds": round(phase5_duration, 1)
            })

            if checkpoint:
                checkpoint.save(phase=5, data={'stac_result': stac_result})

        # =====================================================================
        # SUCCESS
        # =====================================================================
        total_duration = time.time() - start_time

        logger.info("=" * 70)
        logger.info("✅ PROCESS LARGE RASTER COMPLETE - SUCCESS")
        logger.info(f"   Total duration: {total_duration:.2f}s ({total_duration/60:.1f} min)")
        logger.info(f"   Tiles: {tiling_result.get('tile_count', 0)}")
        logger.info(f"   COGs: {len(cog_blobs)}")
        if mosaicjson_result.get('mosaicjson_blob'):
            logger.info(f"   MosaicJSON: {mosaicjson_result.get('mosaicjson_blob')}")
        if stac_result.get('collection_id'):
            logger.info(f"   STAC: {stac_result.get('collection_id')}")
        logger.info("=" * 70)

        return {
            "success": True,
            "result": {
                "tiling": tiling_result,
                "extraction": extraction_result,
                "cogs": {
                    "count": len(cog_blobs),
                    "blobs": cog_blobs,
                },
                "mosaicjson": mosaicjson_result,
                "stac": stac_result,
                "timing": {
                    "total_seconds": round(total_duration, 1),
                    "total_minutes": round(total_duration / 60, 2),
                },
            }
        }

    except Exception as e:
        logger.exception(f"❌ PROCESS LARGE RASTER FAILED: {e}")
        return {
            "success": False,
            "error": "PROCESSING_FAILED",
            "error_type": type(e).__name__,
            "message": str(e),
            "phase": "unknown",
            "tiling": tiling_result,
            "extraction": extraction_result,
        }
