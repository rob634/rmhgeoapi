# ============================================================================
# COREMACHINE FACTORY
# ============================================================================
# STATUS: Core layer - CoreMachine initialization and callbacks
# PURPOSE: Factory function for CoreMachine with Platform integration
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 4 CoreMachine Factory Extraction
# ============================================================================
"""
CoreMachine Factory Module.

Provides factory function for creating CoreMachine instances with proper
callback configuration for Platform integration.

This module extracts ~100 lines of CoreMachine initialization code from
function_app.py to improve modularity and testability.

Features:
    - Platform callback for job completion events
    - STAC item/collection extraction from various result formats
    - Classification extraction for approval workflow
    - Automatic approval record creation for completed jobs

Usage in function_app.py:
    from core.machine_factory import create_core_machine
    from jobs import ALL_JOBS
    from services import ALL_HANDLERS

    core_machine = create_core_machine(ALL_JOBS, ALL_HANDLERS)

Exports:
    create_core_machine: Factory function for CoreMachine instances
    extract_stac_item_id: Helper to extract STAC item ID from results
    extract_stac_collection_id: Helper to extract STAC collection ID
    extract_classification: Helper to extract classification
"""

from typing import Any, Callable, Dict, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.FACTORY, "MachineFactory")


# ============================================================================
# STAC EXTRACTION HELPERS
# ============================================================================

def extract_stac_item_id(result: dict) -> Optional[str]:
    """
    Extract STAC item ID from various result structures.

    Handlers return results in different formats, so we check multiple paths.

    Args:
        result: Job result dict

    Returns:
        STAC item ID if found, None otherwise
    """
    if not result:
        return None

    # Path 1: result.stac.item_id (common pattern)
    if result.get('stac', {}).get('item_id'):
        return result['stac']['item_id']

    # Path 2: result.result.stac.item_id (nested result)
    if result.get('result', {}).get('stac', {}).get('item_id'):
        return result['result']['stac']['item_id']

    # Path 3: result.item_id (flat result)
    if result.get('item_id'):
        return result['item_id']

    # Path 4: result.stac_item_id (alternative key)
    if result.get('stac_item_id'):
        return result['stac_item_id']

    # Path 5: result.result.item_id (nested flat)
    if result.get('result', {}).get('item_id'):
        return result['result']['item_id']

    return None


def extract_stac_collection_id(result: dict) -> Optional[str]:
    """
    Extract STAC collection ID from various result structures.

    Args:
        result: Job result dict

    Returns:
        STAC collection ID if found, None otherwise
    """
    if not result:
        return None

    # Path 1: result.stac.collection_id
    if result.get('stac', {}).get('collection_id'):
        return result['stac']['collection_id']

    # Path 2: result.result.stac.collection_id
    if result.get('result', {}).get('stac', {}).get('collection_id'):
        return result['result']['stac']['collection_id']

    # Path 3: result.collection_id
    if result.get('collection_id'):
        return result['collection_id']

    # Path 4: result.stac_collection_id
    if result.get('stac_collection_id'):
        return result['stac_collection_id']

    # Path 5: result.result.collection_id
    if result.get('result', {}).get('collection_id'):
        return result['result']['collection_id']

    return None


def extract_classification(result: dict) -> str:
    """
    Extract classification from job result (for approval workflow).

    Jobs can specify classification in their parameters. Default is 'ouo'.

    Args:
        result: Job result dict

    Returns:
        Classification string ('ouo' or 'public')
    """
    if not result:
        return 'ouo'

    # Check various locations where classification might be stored
    # Path 1: Direct in result
    if result.get('classification'):
        return result['classification'].lower()

    # Path 2: In parameters
    if result.get('parameters', {}).get('classification'):
        return result['parameters']['classification'].lower()

    # Path 3: In result.result
    if result.get('result', {}).get('classification'):
        return result['result']['classification'].lower()

    # Path 4: access_level mapping (public -> public, everything else -> ouo)
    access_level = result.get('access_level') or result.get('parameters', {}).get('access_level')
    if access_level and access_level.lower() == 'public':
        return 'public'

    return 'ouo'


# ============================================================================
# PLATFORM CALLBACK
# ============================================================================

# Job types that produce datasets requiring approval before publication.
# Approval is linked to job_id (source of truth), not STAC (downstream metadata).
# STAC item/collection IDs are optional enrichment, added when available.
APPROVAL_REQUIRED_JOB_TYPES = {
    # Vector jobs
    'process_vector',               # Function App vector ETL
    'vector_docker_etl',            # Docker vector ETL
    # Raster jobs - Function App
    'process_raster_v2',            # Function App single raster
    'process_large_raster_v2',      # Function App large raster
    'process_raster_collection',    # Function App collection (legacy name)
    'process_raster_collection_v2', # Function App collection v2
    # Raster jobs - Docker
    'process_raster_docker',        # Docker single raster
    'process_large_raster_docker',  # Docker large raster
}


def _default_platform_callback(job_id: str, job_type: str, status: str, result: dict):
    """
    Default callback for Platform orchestration.

    This callback is invoked by CoreMachine when jobs complete.
    Handles:
    1. AssetRelease update (V0.9 - 21 FEB 2026)

    V0.9 Entity Architecture (21 FEB 2026):
    - Updates AssetRelease with processing_status and physical outputs
    - Release was created on request receipt, now updated with outputs
    - Finds release by job_id (not asset_id)

    Approval Philosophy:
    - job_id is the source of truth (not STAC)
    - STAC item/collection IDs are optional enrichment
    - Approval is created for all dataset-producing jobs, regardless of STAC status

    Args:
        job_id: CoreMachine job ID (source of truth for approval)
        job_type: Type of job that completed
        status: 'completed' or 'failed'
        result: Job result dict (may contain STAC IDs for enrichment)

    Note:
        All operations are non-fatal - failures are logged but don't affect job status.
    """
    # =========================================================================
    # V0.9: Update AssetRelease with job outputs (21 FEB 2026)
    # =========================================================================
    # Release was created on request receipt with minimal data.
    # Now update with:
    # - processing_status: completed or failed
    # - Physical outputs: table_name, blob_path, stac_item_id, etc.
    # Release is found by job_id (not asset_id).
    # =========================================================================
    try:
        from infrastructure import ReleaseRepository

        # V0.9: Find release by job_id, update release (not asset)
        release_repo = ReleaseRepository()
        release = release_repo.get_by_job_id(job_id)

        if not release:
            logger.debug(f"[RELEASE] No release linked to job {job_id[:8]}... (pre-V0.9 job or internal job)")
        else:
            # Update processing status
            from core.models.asset import ProcessingStatus
            from datetime import datetime, timezone
            new_status = ProcessingStatus.COMPLETED if status == 'completed' else ProcessingStatus.FAILED
            error_message = result.get('error') or result.get('message') if status != 'completed' else None
            release_repo.update_processing_status(
                release.release_id,
                status=new_status,
                completed_at=datetime.now(timezone.utc),  # 25 FEB 2026: Set for both success AND failure
                error=str(error_message)[:500] if error_message else None
            )

            # Update physical outputs only on success (failed jobs have no valid outputs)
            if status == 'completed':
                outputs = {}

                # Vector: table_name from result
                table_name = result.get('table_name')
                if table_name:
                    outputs['table_name'] = table_name

                # Raster: blob_path from result
                cog_blob = result.get('cog', {}).get('cog_blob') if isinstance(result.get('cog'), dict) else None
                cog_url = cog_blob or result.get('cog_url') or result.get('output_blob_name')
                if cog_url:
                    outputs['blob_path'] = cog_url

                # STAC IDs if available
                stac_item_id = extract_stac_item_id(result)
                if stac_item_id:
                    outputs['stac_item_id'] = stac_item_id

                # Note: stac_collection_id is set at release creation, not updated here

                if outputs:
                    release_repo.update_physical_outputs(release.release_id, **outputs)

            logger.info(f"[RELEASE] Updated release {release.release_id[:12]}... status={new_status}")

    except Exception as e:
        # Non-fatal: release update failure should not affect job completion
        logger.warning(f"[RELEASE] Failed to update release for job {job_id[:8]}... (non-fatal): {e}")

    # =========================================================================
    # V0.9: Approval managed on AssetRelease (21 FEB 2026)
    # =========================================================================
    # Release is created at platform/submit with approval_state=PENDING_REVIEW.
    # Approval state is managed on AssetRelease (not Asset).
    # See: services/asset_approval_service.py
    # =========================================================================


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_core_machine(
    all_jobs: Dict[str, Any],
    all_handlers: Dict[str, Any],
    on_job_complete: Optional[Callable] = None
):
    """
    Create a CoreMachine instance with proper callback configuration.

    This factory function creates CoreMachine with:
    - Explicit job and handler registries (avoiding import timing issues)
    - Platform callback for job completion events
    - Approval workflow integration

    Args:
        all_jobs: Dict mapping job_type -> Job class
        all_handlers: Dict mapping handler_name -> handler function
        on_job_complete: Optional custom callback (defaults to _default_platform_callback)

    Returns:
        Configured CoreMachine instance

    Example:
        from jobs import ALL_JOBS
        from services import ALL_HANDLERS
        from core.machine_factory import create_core_machine

        core_machine = create_core_machine(ALL_JOBS, ALL_HANDLERS)
    """
    from core.machine import CoreMachine

    # Use default platform callback if none provided
    callback = on_job_complete or _default_platform_callback

    core_machine = CoreMachine(
        all_jobs=all_jobs,
        all_handlers=all_handlers,
        on_job_complete=callback
    )

    logger.info("CoreMachine initialized with explicit registries")
    logger.info(f"   Registered jobs: {list(all_jobs.keys())}")
    logger.info(f"   Registered handlers: {list(all_handlers.keys())}")
    logger.info(f"   Platform callback registered")

    return core_machine


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'create_core_machine',
    'extract_stac_item_id',
    'extract_stac_collection_id',
    'extract_classification',
]
