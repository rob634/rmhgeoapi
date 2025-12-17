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
    Verify cell counts for all resolutions using H3 ratio verification.

    Two verification modes:
    1. Absolute: Compare against expected_cells with ±10% tolerance
    2. Ratio: Verify H3 parent-child ratios (7:1 per resolution level)

    For filtered grids (country/bbox), ratio verification is more reliable
    since absolute expected counts are unknown at job submission time.

    Args:
        h3_repo: H3Repository instance
        grid_id_prefix: Grid ID prefix (e.g., "land")
        resolutions: List of resolution levels to verify
        expected_cells: Dict mapping resolution → expected cell count
        logger: Logger instance

    Returns:
        Verification results dict with:
        - all_passed (bool): True if all resolutions pass verification
        - total_cells (int): Sum of actual cells across all resolutions
        - per_resolution (Dict[int, Dict]): Details per resolution
        - failures (List[int]): Resolutions that failed verification
        - verification_mode (str): "absolute" or "ratio"
    """
    logger.info(f"🔍 Verifying cell counts for {len(resolutions)} resolutions...")

    # First, collect all actual counts
    actual_counts = {}
    for resolution in resolutions:
        grid_id = f"{grid_id_prefix}_res{resolution}"
        with h3_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as count FROM h3.grids WHERE grid_id = %s",
                    (grid_id,)
                )
                actual_counts[resolution] = cur.fetchone()['count']

    # Determine verification mode based on expected_cells
    # If expected_cells has hardcoded global values (res2=2000) but actual is different,
    # switch to ratio-based verification
    base_res = min(resolutions)
    expected_base = expected_cells.get(base_res, 0) if isinstance(expected_cells.get(base_res), int) else int(expected_cells.get(str(base_res), 0))
    actual_base = actual_counts.get(base_res, 0)

    # Use ratio verification if expected base doesn't match actual (filtered grid)
    # Tolerance: expected should be within 50% of actual for absolute mode
    use_ratio_mode = (expected_base == 0 or
                      actual_base == 0 or
                      abs(expected_base - actual_base) / max(actual_base, 1) > 0.5)

    if use_ratio_mode:
        logger.info(f"📊 Using RATIO verification (filtered grid detected)")
        verification_mode = "ratio"
    else:
        logger.info(f"📊 Using ABSOLUTE verification")
        verification_mode = "absolute"

    per_resolution_results = {}
    total_cells = 0
    failures = []

    sorted_resolutions = sorted(resolutions)

    for i, resolution in enumerate(sorted_resolutions):
        grid_id = f"{grid_id_prefix}_res{resolution}"
        actual_count = actual_counts[resolution]
        total_cells += actual_count

        if use_ratio_mode:
            # RATIO MODE: Verify H3 7:1 parent-child relationship
            if i == 0:
                # Base resolution - just check it has cells
                passed = actual_count > 0
                expected_count = actual_count  # Self-reference for base
                variance_pct = 0.0
            else:
                # Higher resolutions - should be ~7x previous resolution
                prev_res = sorted_resolutions[i - 1]
                prev_count = actual_counts[prev_res]
                expected_count = prev_count * 7

                # Allow ±15% tolerance for ratio (some edge effects)
                tolerance = 0.15
                min_acceptable = int(expected_count * (1 - tolerance))
                max_acceptable = int(expected_count * (1 + tolerance))
                passed = min_acceptable <= actual_count <= max_acceptable
                variance_pct = round(((actual_count - expected_count) / expected_count) * 100, 2) if expected_count > 0 else 0.0
        else:
            # ABSOLUTE MODE: Compare against expected_cells
            expected_count = expected_cells.get(resolution, 0)
            if isinstance(expected_count, str):
                expected_count = int(expected_count)
            tolerance = 0.10  # ±10%
            min_acceptable = int(expected_count * (1 - tolerance))
            max_acceptable = int(expected_count * (1 + tolerance))
            passed = min_acceptable <= actual_count <= max_acceptable
            variance_pct = round(((actual_count - expected_count) / expected_count) * 100, 2) if expected_count > 0 else 0.0

        per_resolution_results[resolution] = {
            "grid_id": grid_id,
            "actual_count": actual_count,
            "expected_count": expected_count,
            "passed": passed,
            "variance_pct": variance_pct,
            "verification_mode": verification_mode
        }

        if not passed:
            failures.append(resolution)
            logger.warning(
                f"⚠️ Resolution {resolution}: {actual_count:,} cells "
                f"(expected {expected_count:,}, variance {variance_pct}%)"
            )
        else:
            logger.info(
                f"✅ Resolution {resolution}: {actual_count:,} cells "
                f"(expected ~{expected_count:,}, variance {variance_pct}%)"
            )

    return {
        "all_passed": len(failures) == 0,
        "total_cells": total_cells,
        "per_resolution": per_resolution_results,
        "failures": failures,
        "verification_mode": verification_mode
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
    Run VACUUM ANALYZE on h3.grids table to optimize query performance.

    VACUUM reclaims storage and updates statistics for the PostgreSQL query planner.

    Args:
        h3_repo: H3Repository instance
        logger: Logger instance

    Returns:
        True if VACUUM ANALYZE completed successfully
    """
    logger.info("🧹 Running VACUUM ANALYZE on h3.grids...")

    try:
        # VACUUM requires autocommit mode
        with h3_repo._get_connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("VACUUM ANALYZE h3.grids")

        logger.info("✅ VACUUM ANALYZE completed")
        return True

    except Exception as e:
        logger.error(f"⚠️ VACUUM ANALYZE failed (non-critical): {e}")
        return False
