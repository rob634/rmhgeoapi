"""
H3 Multi-Level Cascade Handler.

Generates ALL descendants from a parent grid across multiple resolution levels.

Example:
    Input: 10 res 2 parent cells, target [3,4,5,6,7]
    Output: ~168,070 cells (70 + 490 + 3,430 + 24,010 + 168,070)

Key Properties:
    - No spatial filtering (children inherit parent land membership)
    - Cell-level idempotency (ON CONFLICT DO NOTHING)
    - Batch-level idempotency via H3BatchTracker (resumable jobs)
    - Batch processing support (N parent cells per task)

Exports:
    cascade_h3_descendants: Task handler function
"""

import time
from typing import Dict, Any, List, Tuple
from util_logger import LoggerFactory, ComponentType
import h3
from shapely.geometry import Polygon


def cascade_h3_descendants(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Generate all H3 descendants from parent grid across multiple resolutions.

    Uses H3 parent-child relationships to generate descendants efficiently.
    No spatial operations needed - children inherit parent's land membership.

    Args:
        params: Task parameters containing:
            - parent_grid_id (str): Parent grid to cascade from (e.g., "test_albania_res2")
            - target_resolutions (List[int]): Resolutions to generate (e.g., [3, 4, 5, 6, 7])
            - grid_id_prefix (str): Prefix for grid IDs (e.g., "test_albania")
            - batch_start (int, optional): Starting parent index for batching (default: 0)
            - batch_size (int, optional): Number of parents to process (default: all remaining)
            - batch_index (int, optional): Batch index for idempotency tracking (default: 0)
            - source_job_id (str): Job ID for tracking

        context: Optional execution context (not used in this handler)

    Returns:
        Success dict with generation statistics:
        {
            "success": True,
            "result": {
                "parent_grid_id": str,
                "parents_processed": int,
                "target_resolutions": List[int],
                "cells_per_resolution": {3: 70, 4: 490, ...},
                "total_cells_generated": int,
                "total_cells_inserted": int,
                "elapsed_time": float
            }
        }

        Or failure dict if errors occur:
        {
            "success": False,
            "error": "description of error"
        }

    Raises:
        ValueError: If required parameters missing or invalid

    Example:
        >>> params = {
        ...     "parent_grid_id": "test_albania_res2",
        ...     "target_resolutions": [3, 4, 5, 6, 7],
        ...     "grid_id_prefix": "test_albania",
        ...     "batch_start": 0,
        ...     "batch_size": 10,
        ...     "source_job_id": "abc123..."
        ... }
        >>> result = cascade_h3_descendants(params)
        >>> result["success"]
        True
        >>> result["result"]["total_cells_generated"]
        168070
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "cascade_h3_descendants")
    start_time = time.time()

    # STEP 1: Validate parameters
    parent_grid_id = params.get('parent_grid_id')
    target_resolutions = params.get('target_resolutions')
    grid_id_prefix = params.get('grid_id_prefix')
    batch_start = params.get('batch_start', 0)
    batch_size = params.get('batch_size')  # None = process all remaining
    batch_index = params.get('batch_index', 0)  # For idempotency tracking
    source_job_id = params.get('source_job_id')

    if not parent_grid_id:
        raise ValueError("parent_grid_id is required")

    if not target_resolutions or not isinstance(target_resolutions, list):
        raise ValueError("target_resolutions must be a non-empty list")

    if not grid_id_prefix:
        raise ValueError("grid_id_prefix is required")

    # Generate batch_id for idempotency tracking
    # Format: {job_id_prefix}-s2-batch{index}
    batch_id = f"{source_job_id[:8] if source_job_id else 'unknown'}-s2-batch{batch_index}"

    logger.info(f"🌳 H3 Cascade - Multi-Level Descendants")
    logger.info(f"   Parent Grid: {parent_grid_id}")
    logger.info(f"   Target Resolutions: {target_resolutions}")
    logger.info(f"   Grid ID Prefix: {grid_id_prefix}")
    logger.info(f"   Batch: start={batch_start}, size={batch_size if batch_size else 'ALL'}, id={batch_id}")

    try:
        from infrastructure.h3_repository import H3Repository
        from infrastructure.h3_batch_tracking import H3BatchTracker

        # Create repositories
        h3_repo = H3Repository()
        batch_tracker = H3BatchTracker()

        # STEP 1.5: IDEMPOTENCY CHECK - Skip if batch already completed
        if source_job_id and batch_tracker.is_batch_completed(source_job_id, batch_id):
            logger.info(f"✅ Batch {batch_id} already completed - skipping (idempotent)")
            return {
                "success": True,
                "result": {
                    "skipped": True,
                    "batch_id": batch_id,
                    "message": "Batch already completed (idempotent skip)"
                }
            }

        # Record batch as started
        if source_job_id:
            batch_tracker.start_batch(
                job_id=source_job_id,
                batch_id=batch_id,
                stage_number=2,
                batch_index=batch_index,
                operation_type="cascade_h3_descendants"
            )

        # STEP 2: Verify parent grid exists
        logger.info(f"🔍 Verifying parent grid exists...")
        if not h3_repo.grid_exists(parent_grid_id):
            logger.error(f"❌ Parent grid '{parent_grid_id}' does not exist!")
            return {
                "success": False,
                "error": f"Parent grid '{parent_grid_id}' not found. Cannot cascade."
            }

        # STEP 3: Load parent cells (with batching)
        logger.info(f"📥 Loading parent cells...")
        parent_cells = h3_repo.get_parent_cells(
            parent_grid_id=parent_grid_id,
            batch_start=batch_start,
            batch_size=batch_size
        )

        parents_processed = len(parent_cells)
        logger.info(f"   Loaded {parents_processed:,} parent cells")

        if parents_processed == 0:
            logger.warning(f"⚠️ No parent cells found in batch (start={batch_start}, size={batch_size})")
            return {
                "success": True,
                "result": {
                    "parent_grid_id": parent_grid_id,
                    "parents_processed": 0,
                    "target_resolutions": target_resolutions,
                    "cells_per_resolution": {},
                    "total_cells_generated": 0,
                    "total_cells_inserted": 0,
                    "elapsed_time": time.time() - start_time,
                    "message": "No parents in batch range (end of grid reached)"
                }
            }

        # STEP 4: Cascade to all target resolutions
        logger.info(f"🌳 Cascading to {len(target_resolutions)} resolutions...")

        cells_per_resolution = {}
        total_cells_generated = 0
        total_cells_inserted = 0

        for target_res in sorted(target_resolutions):
            logger.info(f"   → Resolution {target_res}...")

            # Generate descendants for this resolution
            cells, rows_inserted = _cascade_batch(
                h3_repo=h3_repo,
                parent_cells=parent_cells,
                target_resolution=target_res,
                grid_id=f"{grid_id_prefix}_res{target_res}",
                source_job_id=source_job_id,
                logger=logger
            )

            cells_per_resolution[target_res] = len(cells)
            total_cells_generated += len(cells)
            total_cells_inserted += rows_inserted

            logger.info(f"      ✅ Generated {len(cells):,} cells, inserted {rows_inserted:,}")

        # STEP 5: Build success result
        elapsed_time = time.time() - start_time

        logger.info(f"🎉 Cascade complete: {total_cells_inserted:,} cells inserted in {elapsed_time:.2f}s")
        logger.info(f"   Parents processed: {parents_processed:,}")
        logger.info(f"   Resolutions: {target_resolutions}")
        logger.info(f"   Cells per resolution: {cells_per_resolution}")

        # STEP 6: Mark batch as completed (idempotency tracking)
        if source_job_id:
            batch_tracker.complete_batch(
                job_id=source_job_id,
                batch_id=batch_id,
                items_processed=parents_processed,
                items_inserted=total_cells_inserted
            )

        return {
            "success": True,
            "result": {
                "parent_grid_id": parent_grid_id,
                "parents_processed": parents_processed,
                "batch_start": batch_start,
                "batch_size": batch_size,
                "batch_index": batch_index,
                "batch_id": batch_id,
                "target_resolutions": target_resolutions,
                "cells_per_resolution": cells_per_resolution,
                "total_cells_generated": total_cells_generated,
                "total_cells_inserted": total_cells_inserted,
                "elapsed_time": elapsed_time,
                "grid_id_prefix": grid_id_prefix,
                "source_job_id": source_job_id
            }
        }

    except Exception as e:
        logger.error(f"❌ Cascade failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        # Record batch failure (for debugging and retry tracking)
        try:
            from infrastructure.h3_batch_tracking import H3BatchTracker
            batch_tracker = H3BatchTracker()
            if source_job_id:
                batch_tracker.fail_batch(source_job_id, batch_id, str(e))
        except Exception as tracking_error:
            logger.warning(f"Failed to record batch failure: {tracking_error}")

        return {
            "success": False,
            "error": f"Cascade failed: {str(e)}",
            "error_type": type(e).__name__,
            "batch_id": batch_id
        }


def _cascade_batch(
    h3_repo,
    parent_cells: List[Tuple[int, int]],
    target_resolution: int,
    grid_id: str,
    source_job_id: str,
    logger
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Generate descendants at target resolution from batch of parent cells.

    Args:
        h3_repo: H3Repository instance
        parent_cells: List of (h3_index, parent_res2) tuples
        target_resolution: Target resolution level
        grid_id: Grid ID for descendants (e.g., "test_albania_res7")
        source_job_id: Job ID for tracking
        logger: Logger instance

    Returns:
        Tuple of (cells_list, rows_inserted)
        - cells_list: List of cell dicts with h3_index, resolution, geom_wkt
        - rows_inserted: Number of rows actually inserted (excluding conflicts)
    """
    cells = []

    logger.debug(f"   Cascading {len(parent_cells):,} parents to res {target_resolution}...")

    for h3_index, parent_res2 in parent_cells:
        # Convert integer h3_index to hex string for h3 library v4+
        # Database stores BIGINT, but h3 v4 API expects hex strings
        h3_str = h3.int_to_str(h3_index)

        # Generate children at target resolution using H3
        # NOTE: h3.cell_to_children() can jump multiple levels (res 2 → res 7 directly!)
        child_indices = h3.cell_to_children(h3_str, target_resolution)

        for child_index in child_indices:
            # h3 v4 returns hex strings - convert to int for database storage
            # Use h3.str_to_int() for consistent conversion
            if isinstance(child_index, str):
                child_index_int = h3.str_to_int(child_index)
            else:
                child_index_int = int(child_index)

            # Get geometry as WKT (cell_to_boundary returns [(lat, lng), ...])
            boundary = h3.cell_to_boundary(child_index)
            coords = [(lng, lat) for lat, lng in boundary]  # Convert to (lng, lat) for WKT
            coords.append(coords[0])  # Close polygon
            polygon = Polygon(coords)
            geom_wkt = polygon.wkt

            cells.append({
                'h3_index': child_index_int,
                'resolution': target_resolution,
                'geom_wkt': geom_wkt,
                'parent_res2': parent_res2  # Preserve parent for cascade tracking
            })

    logger.debug(f"   Generated {len(cells):,} cells from {len(parent_cells):,} parents")

    # Insert cells to h3.grids
    rows_inserted = _insert_descendants(
        h3_repo=h3_repo,
        cells=cells,
        grid_id=grid_id,
        grid_type='land',  # Descendants inherit parent land membership
        source_job_id=source_job_id,
        logger=logger
    )

    return cells, rows_inserted


def _insert_descendants(
    h3_repo,
    cells: List[Dict[str, Any]],
    grid_id: str,
    grid_type: str,
    source_job_id: str,
    logger
) -> int:
    """
    Insert descendant cells to h3.grids with ON CONFLICT handling.

    Args:
        h3_repo: H3Repository instance
        cells: List of cell dicts (h3_index, resolution, geom_wkt, parent_res2)
        grid_id: Grid ID for cells
        grid_type: Grid type (e.g., "land")
        source_job_id: Job ID for tracking
        logger: Logger instance

    Returns:
        Number of rows actually inserted (excluding conflicts)
    """
    if not cells:
        return 0

    logger.debug(f"   Inserting {len(cells):,} cells to {grid_id}...")

    rows_inserted = h3_repo.insert_h3_cells(
        cells=cells,
        grid_id=grid_id,
        grid_type=grid_type,
        source_job_id=source_job_id
    )

    duplicates_skipped = len(cells) - rows_inserted

    if duplicates_skipped > 0:
        logger.debug(f"   Skipped {duplicates_skipped:,} duplicate cells (ON CONFLICT)")

    return rows_inserted


# ============================================================================
# MODULE EXPORT (Register in services/__init__.py)
# ============================================================================
# To register this handler:
# from .handler_cascade_h3_descendants import cascade_h3_descendants
# ALL_HANDLERS["cascade_h3_descendants"] = cascade_h3_descendants
