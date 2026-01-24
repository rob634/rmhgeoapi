# ============================================================================
# CLAUDE CONTEXT - FATHOM FINALIZE HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler - Stage 3 of process_fathom_docker job
# PURPOSE: Finalize job after all chunks complete
# LAST_REVIEWED: 24 JAN 2026
# EXPORTS: fathom_finalize
# DEPENDENCIES: infrastructure.pgstac_bootstrap
# ============================================================================
"""
FATHOM Finalize Handler - Stage 3.

This handler runs on Azure Functions after all Docker chunks complete:
    1. Validate expected vs actual chunk completion
    2. Update collection extents from items
    3. Aggregate job metrics
    4. Return comprehensive job summary

Duration: ~30 seconds regardless of job size (database operations only)

Future enhancements (not in V0.8):
    - Dynamic pgSTAC extent computation
    - Cross-collection mosaic registration
    - Notification webhooks
    - Quality validation checks
"""

from typing import Dict, List, Any, Set
from util_logger import LoggerFactory, ComponentType


def fathom_finalize(params: dict, context: dict = None) -> dict:
    """
    Finalize job after all chunks complete.

    Runs on: Azure Functions (fast, database operations only)
    Duration: ~30 seconds regardless of job size

    Args:
        params: Task parameters containing:
            - job_id: Job identifier
            - job_parameters: Original job parameters
            - stage1_result: Result from chunk inventory stage
            - chunk_results: List of results from all chunk processing tasks

    Returns:
        dict with:
            - success: True if finalization completed
            - result: Job summary with metrics and validation status
    """
    from infrastructure.pgstac_bootstrap import PgStacBootstrap

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_finalize"
    )

    job_id = params.get('job_id')
    job_params = params.get('job_parameters', {})
    stage1_result = params.get('stage1_result', {})
    chunk_results = params.get('chunk_results', [])

    logger.info(f"📊 FATHOM Finalize - Job: {job_id[:8] if job_id else 'N/A'}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 1: Aggregate results from all chunks
    # ═══════════════════════════════════════════════════════════════
    total_items = 0
    total_tiles = 0
    total_grids = 0
    chunks_succeeded = 0
    chunks_failed = 0
    chunks_interrupted = 0
    collections_updated: Set[str] = set()
    failed_chunks: List[str] = []

    for result in chunk_results:
        if result.get('success'):
            chunks_succeeded += 1
            total_items += result.get('result', {}).get('items_created', 0)
            total_tiles += result.get('result', {}).get('tiles_stacked', 0)
            total_grids += result.get('result', {}).get('grids_merged', 0)

            collection_id = result.get('result', {}).get('collection_id')
            if collection_id:
                collections_updated.add(collection_id)

        elif result.get('interrupted'):
            chunks_interrupted += 1
            # Interrupted chunks can be resumed
            logger.warning(f"   ⚠️ Chunk interrupted: {result.get('chunk_id', 'unknown')}")

        else:
            chunks_failed += 1
            chunk_id = result.get('chunk_id', 'unknown')
            failed_chunks.append(chunk_id)
            logger.error(f"   ❌ Chunk failed: {chunk_id}")
            if result.get('error'):
                logger.error(f"      Error: {result['error']}")

    expected_chunks = stage1_result.get('total_chunks', len(chunk_results))

    logger.info(f"   Chunk results:")
    logger.info(f"      Expected: {expected_chunks}")
    logger.info(f"      Succeeded: {chunks_succeeded}")
    logger.info(f"      Failed: {chunks_failed}")
    logger.info(f"      Interrupted: {chunks_interrupted}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: Update collection extents (if not dry_run)
    # ═══════════════════════════════════════════════════════════════
    if job_params.get('dry_run'):
        logger.info("   🔍 DRY RUN - skipping extent updates")
        extents_updated = []
    else:
        extents_updated = _update_collection_extents(
            collections=list(collections_updated),
            logger=logger
        )

    # ═══════════════════════════════════════════════════════════════
    # STEP 3: Determine overall status
    # ═══════════════════════════════════════════════════════════════
    if chunks_failed == 0 and chunks_interrupted == 0:
        status = 'success'
        status_message = 'All chunks completed successfully'
    elif chunks_succeeded > 0 and (chunks_failed > 0 or chunks_interrupted > 0):
        status = 'partial'
        status_message = f'{chunks_succeeded}/{expected_chunks} chunks completed'
    elif chunks_interrupted > 0 and chunks_failed == 0:
        status = 'interrupted'
        status_message = f'{chunks_interrupted} chunks interrupted (resumable)'
    else:
        status = 'failed'
        status_message = f'All {chunks_failed} chunks failed'

    # ═══════════════════════════════════════════════════════════════
    # STEP 4: Build result
    # ═══════════════════════════════════════════════════════════════
    result = {
        'job_summary': {
            'chunks_expected': expected_chunks,
            'chunks_succeeded': chunks_succeeded,
            'chunks_failed': chunks_failed,
            'chunks_interrupted': chunks_interrupted,
            'total_tiles_stacked': total_tiles,
            'total_grids_merged': total_grids,
            'total_stac_items': total_items,
            'collections_updated': list(collections_updated),
            'extents_updated': extents_updated
        },
        'validation': {
            'status': status,
            'message': status_message,
            'all_chunks_completed': chunks_succeeded == expected_chunks,
            'has_failures': chunks_failed > 0,
            'has_interruptions': chunks_interrupted > 0,
            'failed_chunks': failed_chunks
        },
        'regions_processed': stage1_result.get('regions_in_scope', [])
    }

    logger.info(f"✅ Finalization complete:")
    logger.info(f"   Status: {status}")
    logger.info(f"   Total STAC items: {total_items}")
    logger.info(f"   Collections: {len(collections_updated)}")

    return {
        'success': True,
        'result': result
    }


def _update_collection_extents(
    collections: List[str],
    logger
) -> List[str]:
    """
    Update collection extents from items.

    Queries pgSTAC to compute bounds from all items in collection,
    then updates the collection metadata.

    Args:
        collections: List of collection IDs to update
        logger: Logger instance

    Returns:
        List of collection IDs that were successfully updated
    """
    from infrastructure.pgstac_bootstrap import PgStacBootstrap

    stac_repo = PgStacBootstrap()
    updated = []

    for collection_id in collections:
        try:
            logger.info(f"   Updating extent for: {collection_id}")

            # Compute bounds from items
            bounds = _compute_collection_bounds(collection_id, logger)

            if bounds:
                # Update collection extent
                stac_repo.update_collection_extent(
                    collection_id=collection_id,
                    spatial_bbox=bounds
                )
                updated.append(collection_id)
                logger.info(f"      ✅ Updated: {bounds}")
            else:
                logger.warning(f"      ⚠️ No bounds computed")

        except Exception as e:
            logger.warning(f"      ⚠️ Failed to update extent: {e}")
            continue

    return updated


def _compute_collection_bounds(
    collection_id: str,
    logger
) -> List[float]:
    """
    Compute collection bounds from all items.

    Queries pgSTAC items table to get aggregate bbox.

    Returns:
        Bounding box [west, south, east, north] or None if no items
    """
    from infrastructure import PostgreSQLRepository

    repo = PostgreSQLRepository()

    # Query aggregate bounds from items
    sql = """
        SELECT
            ST_XMin(ST_Extent(geometry::geometry)) as west,
            ST_YMin(ST_Extent(geometry::geometry)) as south,
            ST_XMax(ST_Extent(geometry::geometry)) as east,
            ST_YMax(ST_Extent(geometry::geometry)) as north,
            COUNT(*) as item_count
        FROM pgstac.items
        WHERE collection = %(collection_id)s
    """

    try:
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {'collection_id': collection_id})
                row = cur.fetchone()

                if row and row.get('item_count', 0) > 0:
                    # Check for valid coordinates
                    if all(row.get(k) is not None for k in ['west', 'south', 'east', 'north']):
                        return [
                            row['west'],
                            row['south'],
                            row['east'],
                            row['north']
                        ]

        return None

    except Exception as e:
        logger.warning(f"      ⚠️ Bounds query failed: {e}")
        return None


# Export handler
__all__ = ['fathom_finalize']
