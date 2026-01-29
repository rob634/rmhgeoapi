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
    'process_vector',           # Function App vector ETL
    'vector_docker_etl',        # Docker vector ETL
    'process_raster_v2',        # Function App single raster
    'process_raster_collection', # Function App tiled/collection raster
    'raster_docker_etl',        # Docker raster ETL (if exists)
}


def _default_platform_callback(job_id: str, job_type: str, status: str, result: dict):
    """
    Default callback for Platform orchestration.

    This callback is invoked by CoreMachine when jobs complete.
    Handles:
    1. Approval record creation for dataset-producing jobs (28 JAN 2026)

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
    # Skip if job failed - no approval needed for failed jobs
    if status != 'completed':
        return

    # Skip job types that don't produce datasets requiring approval
    if job_type not in APPROVAL_REQUIRED_JOB_TYPES:
        logger.debug(f"[APPROVAL] Skipping approval for job type '{job_type}' (not in APPROVAL_REQUIRED_JOB_TYPES)")
        return

    # Create approval record for dataset-producing jobs
    # job_id is the source of truth; STAC IDs are optional enrichment
    try:
        from services.approval_service import ApprovalService
        from core.models.stac import AccessLevel

        # Extract STAC IDs if available (optional enrichment, not required)
        stac_item_id = extract_stac_item_id(result)
        stac_collection_id = extract_stac_collection_id(result)

        # Extract classification from job parameters (default: OUO)
        # NOTE: RESTRICTED is not yet supported (future enhancement)
        classification_str = extract_classification(result)
        classification = AccessLevel.PUBLIC if classification_str == 'public' else AccessLevel.OUO

        approval_service = ApprovalService()
        approval = approval_service.create_approval_for_job(
            job_id=job_id,
            job_type=job_type,
            classification=classification,
            stac_item_id=stac_item_id,          # Optional enrichment
            stac_collection_id=stac_collection_id  # Optional enrichment
        )

        # Log with or without STAC info
        stac_info = f", STAC: {stac_item_id}" if stac_item_id else " (no STAC link yet)"
        logger.info(
            f"[APPROVAL] Created approval {approval.approval_id[:12]}... "
            f"for job {job_id[:8]}... (type: {job_type}{stac_info}, status: PENDING)"
        )

    except Exception as e:
        # Non-fatal: approval creation failure should not affect job completion
        logger.warning(f"[APPROVAL] Failed to create approval for job {job_id[:8]}... (non-fatal): {e}")


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
