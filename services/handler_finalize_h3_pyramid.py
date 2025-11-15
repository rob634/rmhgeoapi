# ============================================================================
# CLAUDE CONTEXT - SERVICE HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - H3 pyramid finalization and verification
# PURPOSE: Verify cell counts, update metadata, and finalize H3 bootstrap workflow
# LAST_REVIEWED: 14 NOV 2025
# EXPORTS: finalize_h3_pyramid (task handler function)
# INTERFACES: CoreMachine task handler contract (params, context → result dict)
# PYDANTIC_MODELS: None (uses dict parameters and results)
# DEPENDENCIES: infrastructure.h3_repository.H3Repository, util_logger
# SOURCE: Called by CoreMachine during Stage 7 of bootstrap_h3_land_grid_pyramid job
# SCOPE: Pyramid verification and metadata updates for completed H3 grids
# VALIDATION: Cell count verification against expected values
# PATTERNS: Task handler, PostgreSQL validation, Metadata updates
# ENTRY_POINTS: Registered in services/__init__.py as "finalize_h3_pyramid"
# INDEX: finalize_h3_pyramid:44, verify_cell_counts:73, update_metadata:135
# ============================================================================

"""
H3 Pyramid Finalization Handler

Verifies cell counts, updates h3.grid_metadata, and performs VACUUM ANALYZE
after H3 bootstrap workflow completes.

Stage 7 (Finalization) of bootstrap_h3_land_grid_pyramid workflow.

Author: Robert and Geospatial Claude Legion
Date: 14 NOV 2025
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
    Verify cell counts for all resolutions against expected values.

    Tolerance: ±10% of expected count (land filtering creates variability)

    Args:
        h3_repo: H3Repository instance
        grid_id_prefix: Grid ID prefix (e.g., "land")
        resolutions: List of resolution levels to verify
        expected_cells: Dict mapping resolution → expected cell count
        logger: Logger instance

    Returns:
        Verification results dict with:
        - all_passed (bool): True if all resolutions within tolerance
        - total_cells (int): Sum of actual cells across all resolutions
        - per_resolution (Dict[int, Dict]): Details per resolution
        - failures (List[int]): Resolutions that failed verification
    """
    logger.info(f"🔍 Verifying cell counts for {len(resolutions)} resolutions...")

    per_resolution_results = {}
    total_cells = 0
    failures = []

    for resolution in resolutions:
        grid_id = f"{grid_id_prefix}_res{resolution}"

        # Query actual cell count from h3.grids
        with h3_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM h3.grids WHERE grid_id = %s",
                    (grid_id,)
                )
                actual_count = cur.fetchone()[0]

        # Get expected count (with tolerance)
        expected_count = expected_cells.get(resolution, 0)
        tolerance = 0.10  # ±10%
        min_acceptable = int(expected_count * (1 - tolerance))
        max_acceptable = int(expected_count * (1 + tolerance))

        # Check if within tolerance
        passed = min_acceptable <= actual_count <= max_acceptable

        per_resolution_results[resolution] = {
            "grid_id": grid_id,
            "actual_count": actual_count,
            "expected_count": expected_count,
            "tolerance": f"±{int(tolerance * 100)}%",
            "min_acceptable": min_acceptable,
            "max_acceptable": max_acceptable,
            "passed": passed,
            "variance_pct": round(((actual_count - expected_count) / expected_count) * 100, 2) if expected_count > 0 else 0.0
        }

        total_cells += actual_count

        if not passed:
            failures.append(resolution)
            logger.warning(
                f"⚠️ Resolution {resolution}: {actual_count:,} cells "
                f"(expected {expected_count:,}, variance {per_resolution_results[resolution]['variance_pct']}%)"
            )
        else:
            logger.info(
                f"✅ Resolution {resolution}: {actual_count:,} cells "
                f"(expected {expected_count:,}, variance {per_resolution_results[resolution]['variance_pct']}%)"
            )

    return {
        "all_passed": len(failures) == 0,
        "total_cells": total_cells,
        "per_resolution": per_resolution_results,
        "failures": failures
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
