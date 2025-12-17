# ============================================================================
# CLAUDE CONTEXT - H3 AGGREGATION FINALIZE HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handler - Aggregation Finalization
# PURPOSE: Update stat_registry provenance and verify counts
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: h3_aggregation_finalize
# DEPENDENCIES: infrastructure.h3_repository
# ============================================================================
"""
H3 Aggregation Finalize Handler.

Stage 3 of H3 aggregation workflows. Updates stat_registry with
provenance information and verifies aggregation counts.

Usage:
    result = h3_aggregation_finalize({
        "dataset_id": "worldpop_2020",
        "resolution": 6,
        "total_stats_computed": 176472,
        "total_cells_processed": 176472,
        "source_job_id": "abc123..."
    })
"""

from typing import Dict, Any
from util_logger import LoggerFactory, ComponentType

from .base import validate_dataset_id


def h3_aggregation_finalize(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Finalize H3 aggregation by updating registry provenance.

    Stage 3 handler that:
    1. Validates parameters
    2. Queries actual stat count from h3.zonal_stats or h3.point_stats
    3. Updates stat_registry provenance (last_aggregation_at, cell_count)
    4. Returns verification summary

    Args:
        params: Task parameters containing:
            - dataset_id (str): Dataset identifier
            - resolution (int): H3 resolution level
            - total_stats_computed (int): Stats from Stage 2 (for verification)
            - total_cells_processed (int): Cells from Stage 2
            - source_job_id (str): Job ID for tracking

        context: Optional execution context (not used)

    Returns:
        Success dict with finalization results:
        {
            "success": True,
            "result": {
                "dataset_id": str,
                "resolution": int,
                "total_stats_computed": int,
                "total_cells_processed": int,
                "registry_updated": bool
            }
        }

    Raises:
        ValueError: If required parameters missing or invalid
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_aggregation_finalize")

    # STEP 1: Validate parameters
    dataset_id = params.get('dataset_id')
    resolution = params.get('resolution')
    total_stats_computed = params.get('total_stats_computed', 0)
    total_cells_processed = params.get('total_cells_processed', 0)
    source_job_id = params.get('source_job_id')

    if not dataset_id:
        raise ValueError("dataset_id is required")

    validate_dataset_id(dataset_id)

    logger.info(f"🔍 Finalizing aggregation: {dataset_id}")
    logger.info(f"   Resolution: {resolution}")
    logger.info(f"   Stats reported from Stage 2: {total_stats_computed:,}")
    logger.info(f"   Cells processed: {total_cells_processed:,}")

    try:
        from infrastructure.h3_repository import H3Repository

        h3_repo = H3Repository()

        # STEP 2: Query actual stat count from database
        actual_stat_count = _get_stat_count(h3_repo, dataset_id)
        logger.info(f"   Actual stats in DB: {actual_stat_count:,}")

        # STEP 3: Update stat_registry provenance
        registry_updated = h3_repo.update_stat_registry_provenance(
            id=dataset_id,
            job_id=source_job_id,
            cell_count=total_cells_processed
        )

        if registry_updated:
            logger.info(f"   ✅ Registry provenance updated")
        else:
            logger.warning(f"   ⚠️ Dataset not found in registry: {dataset_id}")

        # STEP 4: Verify counts match (warning only, don't fail)
        if actual_stat_count != total_stats_computed and total_stats_computed > 0:
            variance = abs(actual_stat_count - total_stats_computed) / total_stats_computed * 100
            logger.warning(
                f"   ⚠️ Stat count mismatch: reported={total_stats_computed:,}, "
                f"actual={actual_stat_count:,} (variance: {variance:.1f}%)"
            )

        # STEP 5: Build success result
        logger.info(f"✅ Finalization complete: {dataset_id}")

        return {
            "success": True,
            "result": {
                "dataset_id": dataset_id,
                "resolution": resolution,
                "total_stats_computed": total_stats_computed,
                "total_cells_processed": total_cells_processed,
                "actual_stat_count": actual_stat_count,
                "registry_updated": registry_updated,
                "source_job_id": source_job_id
            }
        }

    except Exception as e:
        logger.error(f"❌ Finalization failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": f"Finalization failed: {str(e)}",
            "error_type": type(e).__name__
        }


def _get_stat_count(h3_repo, dataset_id: str) -> int:
    """
    Get count of stats for dataset from h3.zonal_stats.

    Args:
        h3_repo: H3Repository instance
        dataset_id: Dataset identifier

    Returns:
        Number of stat rows for dataset
    """
    from psycopg import sql

    query = sql.SQL("""
        SELECT COUNT(*) as count
        FROM {schema}.{table}
        WHERE dataset_id = %s
    """).format(
        schema=sql.Identifier('h3'),
        table=sql.Identifier('zonal_stats')
    )

    with h3_repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (dataset_id,))
            result = cur.fetchone()

    return result['count'] if result else 0


# Export for handler registration
__all__ = ['h3_aggregation_finalize']
