# ============================================================================
# PROCESS RASTER COMPLETE HANDLER (Docker)
# ============================================================================
# STATUS: Services - Consolidated raster handler for Docker worker
# PURPOSE: Single handler that does validate → COG → STAC in one execution
# LAST_REVIEWED: 11 JAN 2026
# ============================================================================
"""
Process Raster Complete - Consolidated Docker Handler.

Combines all three stages of raster processing into a single handler:
    1. Validation (CRS, type detection)
    2. COG creation (reproject + compress)
    3. STAC metadata (catalog registration)

Why Consolidated:
    - Docker has no timeout (unlike 10-min Function App limit)
    - Eliminates stage progression overhead
    - Single atomic operation with rollback on failure
    - Reuses existing handler logic

Checkpoint/Resume Support (11 JAN 2026):
    When _task_id is provided in params, uses CheckpointManager for:
    - Phase tracking (skip completed phases on resume)
    - Artifact validation (ensure outputs exist before saving checkpoint)
    - Data persistence (pass results between phases on resume)

    Resume scenario: Docker crashes after Phase 2 (COG created).
    On restart, CheckpointManager detects phase=2 completed,
    skips phases 1-2, and continues with Phase 3 (STAC).

Exports:
    process_raster_complete: Consolidated handler function
"""

import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def process_raster_complete(params: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Complete raster processing in single execution.

    Consolidates validate → COG → STAC into one handler.
    Designed for Docker worker with no timeout constraints.

    Args:
        params: Task parameters with:
            - _task_id: Task ID for checkpoint tracking (optional but recommended)
            - blob_url: Azure blob URL with SAS token
            - blob_name: Source blob path
            - container_name: Source container
            - input_crs: Optional source CRS override
            - target_crs: Target CRS for reprojection
            - raster_type: 'auto', 'rgb', 'rgba', 'dem', etc.
            - output_blob_name: COG output path
            - output_tier: 'visualization', 'analysis', 'archive'
            - collection_id: STAC collection
            - item_id: Optional STAC item ID
            - use_windowed_read: Enable chunked processing for large files
            - chunk_size_mb: Window size for chunked processing
        context: Optional context (not used in Docker mode)

    Returns:
        dict: Combined result with validation, cog, and stac sections

    Resume Behavior:
        If _task_id is provided and task has existing checkpoint:
        - Phase 1 (validation): Skipped if checkpoint_phase >= 1
        - Phase 2 (COG): Skipped if checkpoint_phase >= 2
        - Phase 3 (STAC): Skipped if checkpoint_phase >= 3
        Checkpoint data provides inputs for resumed phases.
    """
    start_time = time.time()

    blob_name = params.get('blob_name', 'unknown')
    container_name = params.get('container_name', 'unknown')
    task_id = params.get('_task_id')

    logger.info("=" * 60)
    logger.info("PROCESS RASTER COMPLETE - Docker Handler")
    logger.info(f"Source: {container_name}/{blob_name}")
    if task_id:
        logger.info(f"Task ID: {task_id[:8]}... (checkpoint enabled)")
    logger.info("=" * 60)

    # Initialize checkpoint manager if task_id provided
    checkpoint = None
    if task_id:
        try:
            from infrastructure import CheckpointManager
            from infrastructure.factory import RepositoryFactory
            task_repo = RepositoryFactory.create_task_repository()
            checkpoint = CheckpointManager(task_id, task_repo)
            if checkpoint.current_phase > 0:
                logger.info(f"🔄 Resuming from phase {checkpoint.current_phase}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize CheckpointManager: {e}")
            checkpoint = None

    # Track results from each phase
    validation_result = {}
    cog_result = {}
    stac_result = {}

    # Track timing (may be partial on resume)
    phase1_duration = 0.0
    phase2_duration = 0.0
    phase3_duration = 0.0

    try:
        # =====================================================================
        # PHASE 1: VALIDATION
        # =====================================================================
        if checkpoint and checkpoint.should_skip(1):
            logger.info("⏭️ PHASE 1: Skipping validation (already completed)")
            # Restore validation result from checkpoint
            validation_result = checkpoint.get_data('validation_result', {})
            source_crs = checkpoint.get_data('source_crs')
            if not source_crs:
                logger.error("Resume error: No source_crs in checkpoint data")
                return {
                    "success": False,
                    "error": "CHECKPOINT_MISSING_DATA",
                    "message": "Checkpoint missing source_crs from phase 1",
                    "phase": "resume_validation",
                }
        else:
            logger.info("🔄 PHASE 1: Validating raster...")
            phase1_start = time.time()

            from .raster_validation import validate_raster

            validation_params = {
                'blob_url': params.get('blob_url'),
                'blob_name': blob_name,
                'container_name': container_name,
                'input_crs': params.get('input_crs'),
                'raster_type': params.get('raster_type', 'auto'),
                'strict_mode': params.get('strict_mode', False),
            }

            validation_response = validate_raster(validation_params)

            if not validation_response.get('success'):
                logger.error(f"Validation failed: {validation_response.get('error')}")
                return {
                    "success": False,
                    "error": "VALIDATION_FAILED",
                    "message": validation_response.get('message', 'Validation failed'),
                    "phase": "validation",
                    "validation": validation_response,
                }

            validation_result = validation_response.get('result', {})
            source_crs = validation_result.get('source_crs')

            if not source_crs:
                logger.error("No source_crs in validation results")
                return {
                    "success": False,
                    "error": "NO_SOURCE_CRS",
                    "message": "Validation did not return source CRS",
                    "phase": "validation",
                    "validation": validation_result,
                }

            phase1_duration = time.time() - phase1_start
            logger.info(f"✅ PHASE 1 complete: {phase1_duration:.2f}s")
            logger.info(f"  Source CRS: {source_crs}")
            logger.info(f"  Raster type: {validation_result.get('raster_type', {}).get('detected_type')}")

            # Save checkpoint after phase 1
            if checkpoint:
                checkpoint.save(
                    phase=1,
                    data={
                        'source_crs': source_crs,
                        'validation_result': validation_result,
                    }
                )

        # =====================================================================
        # PHASE 2: COG CREATION
        # =====================================================================
        from config import get_config
        config = get_config()

        if checkpoint and checkpoint.should_skip(2):
            logger.info("⏭️ PHASE 2: Skipping COG creation (already completed)")
            # Restore COG result from checkpoint
            cog_result = checkpoint.get_data('cog_result', {})
            cog_blob = checkpoint.get_data('cog_blob')
            cog_container = checkpoint.get_data('cog_container') or config.storage.silver.cogs
            if not cog_blob:
                logger.error("Resume error: No cog_blob in checkpoint data")
                return {
                    "success": False,
                    "error": "CHECKPOINT_MISSING_DATA",
                    "message": "Checkpoint missing cog_blob from phase 2",
                    "phase": "resume_cog",
                }
        else:
            logger.info("🔄 PHASE 2: Creating COG...")
            phase2_start = time.time()

            from .raster_cog import create_cog

            cog_params = {
                'blob_name': blob_name,
                'container_name': container_name,
                'source_crs': source_crs,
                'target_crs': params.get('target_crs') or config.raster.target_crs,
                'raster_type': validation_result.get('raster_type', {}),
                'output_blob_name': params.get('output_blob_name'),
                'output_tier': params.get('output_tier', 'analysis'),
                'jpeg_quality': params.get('jpeg_quality') or config.raster.cog_jpeg_quality,
                'overview_resampling': params.get('overview_resampling') or config.raster.overview_resampling,
                'reproject_resampling': params.get('reproject_resampling') or config.raster.reproject_resampling,
                'in_memory': False,  # Docker uses disk for large files
            }

            cog_response = create_cog(cog_params)

            if not cog_response.get('success'):
                logger.error(f"COG creation failed: {cog_response.get('error')}")
                return {
                    "success": False,
                    "error": "COG_CREATION_FAILED",
                    "message": cog_response.get('message', 'COG creation failed'),
                    "phase": "cog_creation",
                    "validation": validation_result,
                    "cog": cog_response,
                }

            cog_result = cog_response.get('result', {})
            cog_blob = cog_result.get('output_blob') or cog_result.get('cog_blob')
            cog_container = cog_result.get('cog_container') or config.storage.silver.cogs

            if not cog_blob:
                logger.error("COG creation did not return output blob path")
                return {
                    "success": False,
                    "error": "NO_COG_OUTPUT",
                    "message": "COG creation did not return output blob path",
                    "phase": "cog_creation",
                    "validation": validation_result,
                    "cog": cog_result,
                }

            phase2_duration = time.time() - phase2_start
            logger.info(f"✅ PHASE 2 complete: {phase2_duration:.2f}s")
            logger.info(f"  COG blob: {cog_blob}")
            logger.info(f"  Size: {cog_result.get('size_mb', 'unknown')} MB")

            # Save checkpoint after phase 2 with artifact validation
            if checkpoint:
                from infrastructure.blob import BlobRepository

                def validate_cog_exists():
                    """Validate COG blob exists before saving checkpoint."""
                    try:
                        blob_repo = BlobRepository.for_zone('silver')
                        return blob_repo.blob_exists(cog_container, cog_blob)
                    except Exception as e:
                        logger.warning(f"COG validation failed: {e}")
                        return False

                checkpoint.save(
                    phase=2,
                    data={
                        'cog_blob': cog_blob,
                        'cog_container': cog_container,
                        'cog_result': cog_result,
                    },
                    validate_artifact=validate_cog_exists
                )

        # =====================================================================
        # PHASE 3: STAC METADATA
        # =====================================================================
        if checkpoint and checkpoint.should_skip(3):
            logger.info("⏭️ PHASE 3: Skipping STAC metadata (already completed)")
            # Restore STAC result from checkpoint
            stac_result = checkpoint.get_data('stac_result', {})
        else:
            logger.info("🔄 PHASE 3: Creating STAC metadata...")
            phase3_start = time.time()

            from .stac_catalog import extract_stac_metadata

            stac_params = {
                'container_name': cog_container,
                'blob_name': cog_blob,
                'collection_id': params.get('collection_id') or config.raster.stac_default_collection,
                'item_id': params.get('item_id'),
                # Platform passthrough
                'dataset_id': params.get('dataset_id'),
                'resource_id': params.get('resource_id'),
                'version_id': params.get('version_id'),
                'access_level': params.get('access_level'),
                # Raster type for visualization
                'raster_type': cog_result.get('raster_type'),
            }

            stac_response = extract_stac_metadata(stac_params)

            if not stac_response.get('success'):
                # STAC failure is non-fatal - COG was created successfully
                logger.warning(f"STAC creation failed (non-fatal): {stac_response.get('error')}")
                stac_result = {
                    "degraded": True,
                    "error": stac_response.get('error'),
                    "message": stac_response.get('message', 'STAC creation failed'),
                }
            else:
                stac_result = stac_response.get('result', {})

            phase3_duration = time.time() - phase3_start
            logger.info(f"✅ PHASE 3 complete: {phase3_duration:.2f}s")
            if stac_result.get('item_id'):
                logger.info(f"  STAC item: {stac_result.get('item_id')}")

            # Save checkpoint after phase 3 (all phases complete)
            if checkpoint:
                checkpoint.save(
                    phase=3,
                    data={
                        'stac_result': stac_result,
                    }
                )

        # =====================================================================
        # SUCCESS
        # =====================================================================
        total_duration = time.time() - start_time

        # Determine if this was a resumed execution
        resumed_from_phase = checkpoint.current_phase if checkpoint and checkpoint.current_phase > 0 else None
        phases_skipped = []
        if resumed_from_phase:
            if resumed_from_phase >= 1:
                phases_skipped.append("validation")
            if resumed_from_phase >= 2:
                phases_skipped.append("cog_creation")
            if resumed_from_phase >= 3:
                phases_skipped.append("stac_metadata")

        logger.info("=" * 60)
        logger.info("PROCESS RASTER COMPLETE - SUCCESS")
        if resumed_from_phase:
            logger.info(f"🔄 Resumed from phase {resumed_from_phase} (skipped: {', '.join(phases_skipped)})")
        logger.info(f"Total duration: {total_duration:.2f}s")
        if phase1_duration > 0:
            logger.info(f"  Validation: {phase1_duration:.2f}s")
        if phase2_duration > 0:
            logger.info(f"  COG creation: {phase2_duration:.2f}s")
        if phase3_duration > 0:
            logger.info(f"  STAC metadata: {phase3_duration:.2f}s")
        logger.info("=" * 60)

        return {
            "success": True,
            "result": {
                "validation": {
                    "source_crs": source_crs,
                    "raster_type": validation_result.get('raster_type', {}).get('detected_type'),
                    "confidence": validation_result.get('raster_type', {}).get('confidence'),
                    "warnings": validation_result.get('warnings', []),
                },
                "cog": {
                    "cog_blob": cog_blob,
                    "cog_container": cog_container,
                    "size_mb": cog_result.get('size_mb'),
                    "compression": cog_result.get('compression'),
                    "processing_time_seconds": phase2_duration,
                    "raster_type": cog_result.get('raster_type'),
                },
                "stac": stac_result,
                "processing": {
                    "total_seconds": total_duration,
                    "validation_seconds": phase1_duration,
                    "cog_seconds": phase2_duration,
                    "stac_seconds": phase3_duration,
                    "mode": "docker_single_stage",
                    "resumed": resumed_from_phase is not None,
                    "resumed_from_phase": resumed_from_phase,
                    "phases_skipped": phases_skipped,
                },
            },
        }

    except Exception as e:
        import traceback
        total_duration = time.time() - start_time

        # Get checkpoint state for debugging
        checkpoint_state = None
        if checkpoint:
            checkpoint_state = {
                "current_phase": checkpoint.current_phase,
                "data_keys": list(checkpoint.data.keys()),
            }

        logger.error("=" * 60)
        logger.error("PROCESS RASTER COMPLETE - FAILED")
        logger.error(f"Error: {e}")
        logger.error(f"Duration before failure: {total_duration:.2f}s")
        if checkpoint_state:
            logger.error(f"Checkpoint state: phase={checkpoint_state['current_phase']}, keys={checkpoint_state['data_keys']}")
        logger.error("=" * 60)
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
            "validation": validation_result,
            "cog": cog_result,
            "stac": stac_result,
            "duration_seconds": total_duration,
            "checkpoint_state": checkpoint_state,
        }
