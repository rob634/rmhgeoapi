"""
H3 Pyramid Finalization Handler.

Verifies cell counts, updates h3.grid_metadata, and performs VACUUM ANALYZE
after H3 bootstrap workflow completes.

Final stage of bootstrap_h3_land_grid_pyramid workflow.

Exports:
    finalize_h3_pyramid: Task handler function
"""

from typing import Dict, Any, List
from util_logger import LoggerFactory, ComponentType


def finalize_h3_pyramid(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Finalize H3 pyramid after all resolution levels are generated.

    Performs:
    1. Verify cell counts against expected values (tolerance check)
    2. Update h3.grid_metadata with completion status and statistics
    3. Run VACUUM ANALYZE on h3.grids table for query optimization
    4. Return comprehensive verification report

    Args:
        params: Task parameters containing:
            - grid_id_prefix (str): Grid ID prefix (e.g., "land")
            - resolutions (List[int]): Resolution levels to verify (e.g., [2, 3, 4, 5, 6, 7])
            - expected_cells (Dict[int, int]): Expected cell counts per resolution
            - source_job_id (str): Bootstrap job ID

        context: Optional execution context (not used in this handler)

    Returns:
        Success dict with verification results:
        {
            "success": True,
            "result": {
                "verified_resolutions": List[int],
                "total_cells": int,
                "verification_details": Dict[str, Any],
                "metadata_updated": bool,
                "vacuum_completed": bool
            }
        }

        Or failure dict if verification fails:
        {
            "success": False,
            "error": "description of verification failure"
        }

    Raises:
        ValueError: If required parameters missing
        Exception: Database connection or query errors (caught and returned as failure)
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "finalize_h3_pyramid")

    # STEP 1: Validate parameters
    grid_id_prefix = params.get('grid_id_prefix')
    resolutions = params.get('resolutions')
    expected_cells = params.get('expected_cells', {})
    source_job_id = params.get('source_job_id')

    if not grid_id_prefix:
        raise ValueError("grid_id_prefix is required")

    if not resolutions or not isinstance(resolutions, list):
        raise ValueError("resolutions must be a non-empty list")

    logger.info(f"🔍 Finalizing H3 pyramid: {grid_id_prefix} (resolutions {resolutions})")

    try:
        from infrastructure.h3_repository import H3Repository

        # Create repository
        h3_repo = H3Repository()

        # STEP 2: Verify cell counts for all resolutions
        verification_results = _verify_cell_counts(
            h3_repo=h3_repo,
            grid_id_prefix=grid_id_prefix,
            resolutions=resolutions,
            expected_cells=expected_cells,
            logger=logger
        )

        # Check if verification passed
        if not verification_results['all_passed']:
            logger.error(f"❌ Cell count verification failed: {verification_results['failures']}")
            return {
                "success": False,
                "error": f"Cell count verification failed for resolutions: {verification_results['failures']}",
                "verification_details": verification_results
            }

        logger.info(f"✅ Cell count verification passed for all {len(resolutions)} resolutions")

        # STEP 3: Update h3.grid_metadata with completion status
        metadata_updated = _update_grid_metadata(
            h3_repo=h3_repo,
            grid_id_prefix=grid_id_prefix,
            resolutions=resolutions,
            verification_results=verification_results,
            source_job_id=source_job_id,
            logger=logger
        )

        # STEP 4: Run VACUUM ANALYZE on h3.grids for query optimization
        vacuum_completed = _vacuum_analyze_grids(h3_repo, logger)

        # STEP 5: Build success result
        total_cells = verification_results['total_cells']
        logger.info(f"🎉 H3 pyramid finalized: {total_cells:,} cells across {len(resolutions)} resolutions")

        return {
            "success": True,
            "result": {
                "verified_resolutions": resolutions,
                "total_cells": total_cells,
                "verification_details": verification_results,
                "metadata_updated": metadata_updated,
                "vacuum_completed": vacuum_completed,
                "grid_id_prefix": grid_id_prefix,
                "source_job_id": source_job_id
            }
        }

    except Exception as e:
        logger.error(f"❌ Finalization failed: {e}")
        return {
            "success": False,
            "error": f"Finalization failed: {str(e)}",
            "error_type": type(e).__name__
        }


def _verify_cell_counts(
    h3_repo,
    grid_id_prefix: str,
    resolutions: List[int],
    expected_cells: Dict[int, int],
    logger
) -> Dict[str, Any]:
    """
    Verify H3 cell counts using 7:1 ratio verification.

    Uses NORMALIZED h3.cells table (not legacy h3.grids).
    H3 property: each parent cell has exactly 7 children.
    We verify each resolution has ~7× the cells of the previous resolution.

    Args:
        h3_repo: H3Repository instance
        grid_id_prefix: Grid ID prefix (for logging only - normalized schema uses resolution)
        resolutions: List of resolution levels to verify
        expected_cells: Dict mapping resolution → expected count (ignored, kept for API compat)
        logger: Logger instance

    Returns:
        Verification results dict with:
        - all_passed (bool): True if all resolutions pass
        - total_cells (int): Sum of cells across all resolutions
        - per_resolution (Dict): Details per resolution
        - failures (List[int]): Resolutions that failed
    """
    TOLERANCE = 0.05  # ±5% deviation allowed

    logger.info(f"🔍 Verifying H3 ratios for {len(resolutions)} resolutions (±{TOLERANCE*100:.0f}% tolerance)")

    # Get actual counts from NORMALIZED h3.cells table
    actual_counts = {}
    for resolution in resolutions:
        # Query by resolution (normalized schema - no grid_id)
        actual_counts[resolution] = h3_repo.get_cell_count_by_resolution(resolution)

    # Verify ratios
    sorted_res = sorted(resolutions)
    per_resolution = {}
    total_cells = 0
    failures = []

    for i, res in enumerate(sorted_res):
        actual = actual_counts[res]
        total_cells += actual

        if i == 0:
            # Base resolution: just needs cells > 0
            passed = actual > 0
            expected = actual
            ratio = 1.0
        else:
            # Check 7:1 ratio with previous resolution
            prev_res = sorted_res[i - 1]
            prev_count = actual_counts[prev_res]
            expected = prev_count * 7
            ratio = actual / expected if expected > 0 else 0

            # Pass if within ±5% of expected
            passed = (1 - TOLERANCE) <= ratio <= (1 + TOLERANCE)

        per_resolution[res] = {
            "grid_id": f"{grid_id_prefix}_res{res}",  # For logging compatibility
            "actual_count": actual,
            "expected_count": expected,
            "ratio": round(ratio, 4),
            "passed": passed,
            "variance_pct": round((ratio - 1.0) * 100, 2) if expected > 0 else 0
        }

        if passed:
            logger.info(f"✅ Res {res}: {actual:,} cells (ratio: {ratio:.4f})")
        else:
            failures.append(res)
            logger.warning(f"❌ Res {res}: {actual:,} cells (expected {expected:,}, ratio: {ratio:.4f})")

    all_passed = len(failures) == 0
    logger.info(f"{'✅' if all_passed else '❌'} Verification: {total_cells:,} total cells, {len(failures)} failures")

    return {
        "all_passed": all_passed,
        "total_cells": total_cells,
        "per_resolution": per_resolution,
        "failures": failures,
        "tolerance": TOLERANCE
    }


def _update_grid_metadata(
    h3_repo,
    grid_id_prefix: str,
    resolutions: List[int],
    verification_results: Dict[str, Any],
    source_job_id: str,
    logger
) -> bool:
    """
    Update h3.grid_metadata table with completion status and statistics.

    Creates or updates metadata record for each resolution level.

    Args:
        h3_repo: H3Repository instance
        grid_id_prefix: Grid ID prefix (e.g., "land")
        resolutions: List of resolution levels
        verification_results: Results from cell count verification
        source_job_id: Bootstrap job ID
        logger: Logger instance

    Returns:
        True if metadata updated successfully
    """
    logger.info(f"📝 Updating h3.grid_metadata for {len(resolutions)} resolutions...")

    try:
        with h3_repo._get_connection() as conn:
            with conn.cursor() as cur:
                for resolution in resolutions:
                    grid_id = f"{grid_id_prefix}_res{resolution}"
                    res_results = verification_results['per_resolution'][resolution]

                    # Upsert metadata record
                    cur.execute(
                        """
                        INSERT INTO h3.grid_metadata (
                            grid_id,
                            resolution,
                            grid_type,
                            cell_count,
                            generation_status,
                            source_job_id,
                            metadata,
                            created_at,
                            updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                        )
                        ON CONFLICT (grid_id)
                        DO UPDATE SET
                            cell_count = EXCLUDED.cell_count,
                            generation_status = EXCLUDED.generation_status,
                            metadata = h3.grid_metadata.metadata || EXCLUDED.metadata,
                            updated_at = NOW()
                        """,
                        (
                            grid_id,
                            resolution,
                            'land',  # Grid type (from prefix)
                            res_results['actual_count'],
                            'completed',
                            source_job_id,
                            {
                                "expected_count": res_results['expected_count'],
                                "variance_pct": res_results['variance_pct'],
                                "verification_passed": res_results['passed'],
                                "finalized_at": "NOW()"  # PostgreSQL function
                            }
                        )
                    )

            conn.commit()

        logger.info(f"✅ Metadata updated for {len(resolutions)} resolutions")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to update metadata: {e}")
        return False


def _vacuum_analyze_grids(h3_repo, logger) -> bool:
    """
    Run VACUUM ANALYZE on h3.cells table to optimize query performance.

    Uses NORMALIZED h3.cells table (not legacy h3.grids).
    VACUUM reclaims storage and updates statistics for the PostgreSQL query planner.

    Args:
        h3_repo: H3Repository instance
        logger: Logger instance

    Returns:
        True if VACUUM ANALYZE completed successfully
    """
    logger.info("🧹 Running VACUUM ANALYZE on h3.cells...")

    try:
        # VACUUM requires autocommit mode
        with h3_repo._get_connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("VACUUM ANALYZE h3.cells")

        logger.info("✅ VACUUM ANALYZE completed")
        return True

    except Exception as e:
        logger.error(f"⚠️ VACUUM ANALYZE failed (non-critical): {e}")
        return False
