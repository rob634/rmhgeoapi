"""
H3 Multi-Level Cascade Handler.

Generates ALL descendants from a parent grid across multiple resolution levels.

Example:
    Input: 10 res 2 parent cells, target [3,4,5,6,7]
    Output: ~196,070 cells (70 + 490 + 3,430 + 24,010 + 168,070)

Key Properties:
    - No spatial filtering (children inherit parent land membership)
    - Cell-level idempotency (ON CONFLICT DO NOTHING)
    - Batch-level idempotency via H3BatchTracker (resumable jobs)
    - Memory-optimized: generate ALL cells first, then ONE connection for insert
    - Database I/O optimized: single connection per task (22 DEC 2025)

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

    OPTIMIZATION (22 DEC 2025):
        - Generate ALL cells in memory first (~114MB for 196K cells)
        - Open ONE database connection
        - Batch insert all cells + admin0 mappings
        - Close connection
        This reduces connections from ~15 per task to 1 per task.

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
        Success dict with generation statistics
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "cascade_h3_descendants")
    start_time = time.time()

    # STEP 1: Validate parameters
    parent_grid_id = params.get('parent_grid_id')
    target_resolutions = params.get('target_resolutions')
    grid_id_prefix = params.get('grid_id_prefix')
    batch_start = params.get('batch_start', 0)
    batch_size = params.get('batch_size')
    batch_index = params.get('batch_index', 0)
    source_job_id = params.get('source_job_id')
    country_code = params.get('country_code')

    if not parent_grid_id:
        raise ValueError("parent_grid_id is required")

    if not target_resolutions or not isinstance(target_resolutions, list):
        raise ValueError("target_resolutions must be a non-empty list")

    if not grid_id_prefix:
        raise ValueError("grid_id_prefix is required")

    batch_id = f"{source_job_id[:8] if source_job_id else 'unknown'}-s2-batch{batch_index}"

    logger.info(f"🌳 H3 Cascade - Multi-Level Descendants (Memory-Optimized)")
    logger.info(f"   Parent Grid: {parent_grid_id}")
    logger.info(f"   Target Resolutions: {target_resolutions}")
    logger.info(f"   Batch: start={batch_start}, size={batch_size if batch_size else 'ALL'}, id={batch_id}")

    try:
        from infrastructure.h3_repository import H3Repository
        from infrastructure.h3_batch_tracking import H3BatchTracker

        h3_repo = H3Repository()
        batch_tracker = H3BatchTracker()

        # IDEMPOTENCY CHECK
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

        # STEP 2: Load parent cells (uses one connection, closes it)
        logger.info(f"📥 Loading parent cells from h3.cells...")
        parent_cells = h3_repo.get_cells_by_resolution(
            resolution=2,
            batch_start=batch_start,
            batch_size=batch_size
        )

        parents_processed = len(parent_cells)
        logger.info(f"   Loaded {parents_processed:,} parent cells")

        if parents_processed == 0:
            logger.warning(f"⚠️ No parent cells found in batch")
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
                    "message": "No parents in batch range"
                }
            }

        # ====================================================================
        # STEP 3: GENERATE ALL CELLS IN MEMORY (no DB connections)
        # ====================================================================
        logger.info(f"🧠 Generating all cells in memory...")
        gen_start = time.time()

        all_cells = []
        cells_per_resolution = {}

        for target_res in sorted(target_resolutions):
            res_cells = _generate_descendants(parent_cells, target_res)
            cells_per_resolution[target_res] = len(res_cells)
            all_cells.extend(res_cells)
            logger.info(f"   Res {target_res}: {len(res_cells):,} cells")

        gen_elapsed = time.time() - gen_start
        logger.info(f"   Generated {len(all_cells):,} total cells in {gen_elapsed:.2f}s")

        # ====================================================================
        # STEP 4: ONE CONNECTION - BATCH INSERT EVERYTHING
        # ====================================================================
        logger.info(f"💾 Inserting all cells with ONE connection...")
        insert_start = time.time()

        rows_inserted, admin0_inserted = _insert_all_cells(
            h3_repo=h3_repo,
            cells=all_cells,
            source_job_id=source_job_id,
            country_code=country_code,
            logger=logger
        )

        insert_elapsed = time.time() - insert_start
        logger.info(f"   Inserted {rows_inserted:,} cells + {admin0_inserted:,} admin0 in {insert_elapsed:.2f}s")

        # STEP 5: Mark batch complete
        elapsed_time = time.time() - start_time

        if source_job_id:
            batch_tracker.complete_batch(
                job_id=source_job_id,
                batch_id=batch_id,
                items_processed=parents_processed,
                items_inserted=rows_inserted
            )

        logger.info(f"🎉 Cascade complete: {rows_inserted:,} cells in {elapsed_time:.2f}s")

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
                "total_cells_generated": len(all_cells),
                "total_cells_inserted": rows_inserted,
                "admin0_inserted": admin0_inserted,
                "generation_time": gen_elapsed,
                "insert_time": insert_elapsed,
                "elapsed_time": elapsed_time,
                "grid_id_prefix": grid_id_prefix,
                "source_job_id": source_job_id
            }
        }

    except Exception as e:
        logger.error(f"❌ Cascade failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

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


def _generate_descendants(
    parent_cells: List[Tuple[int, int]],
    target_resolution: int
) -> List[Dict[str, Any]]:
    """
    Generate H3 descendants at target resolution (pure CPU, no DB).

    Args:
        parent_cells: List of (h3_index, parent_res2) tuples
        target_resolution: Target resolution level

    Returns:
        List of cell dicts with h3_index, resolution, geom_wkt, is_land
    """
    cells = []

    for h3_index, parent_res2 in parent_cells:
        h3_str = h3.int_to_str(h3_index)
        child_indices = h3.cell_to_children(h3_str, target_resolution)

        for child_index in child_indices:
            if isinstance(child_index, str):
                child_index_int = h3.str_to_int(child_index)
            else:
                child_index_int = int(child_index)

            boundary = h3.cell_to_boundary(child_index)
            coords = [(lng, lat) for lat, lng in boundary]
            coords.append(coords[0])
            polygon = Polygon(coords)

            cells.append({
                'h3_index': child_index_int,
                'resolution': target_resolution,
                'geom_wkt': polygon.wkt,
                'is_land': True
            })

    return cells


def _insert_all_cells(
    h3_repo,
    cells: List[Dict[str, Any]],
    source_job_id: str,
    country_code: str,
    logger
) -> Tuple[int, int]:
    """
    Insert all cells and admin0 mappings using ONE database connection.

    Args:
        h3_repo: H3Repository instance
        cells: List of all cell dicts
        source_job_id: Job ID for tracking
        country_code: ISO3 code for admin0 mappings
        logger: Logger instance

    Returns:
        Tuple of (cells_inserted, admin0_inserted)
    """
    from io import StringIO

    if not cells:
        return 0, 0

    with h3_repo._get_connection() as conn:
        with conn.cursor() as cur:
            # ============================================================
            # INSERT CELLS via COPY + staging
            # ============================================================
            cur.execute("""
                CREATE TEMP TABLE h3_cells_staging (
                    h3_index BIGINT,
                    resolution SMALLINT,
                    geom_wkt TEXT,
                    is_land BOOLEAN
                ) ON COMMIT DROP
            """)

            buffer = StringIO()
            for cell in cells:
                h3_index = cell['h3_index']
                resolution = cell['resolution']
                geom_wkt = cell['geom_wkt']
                is_land = 't' if cell.get('is_land', True) else 'f'
                buffer.write(f"{h3_index}\t{resolution}\t{geom_wkt}\t{is_land}\n")

            buffer.seek(0)
            with cur.copy("COPY h3_cells_staging (h3_index, resolution, geom_wkt, is_land) FROM STDIN") as copy:
                copy.write(buffer.read())

            # Insert from staging with ON CONFLICT
            cur.execute(f"""
                INSERT INTO h3.cells (h3_index, resolution, geom, is_land, source_job_id)
                SELECT
                    h3_index,
                    resolution,
                    ST_GeomFromText(geom_wkt, 4326),
                    is_land,
                    %s
                FROM h3_cells_staging
                ON CONFLICT (h3_index) DO NOTHING
            """, (source_job_id,))

            rows_inserted = cur.rowcount
            logger.debug(f"   Cells inserted: {rows_inserted:,}")

            # ============================================================
            # INSERT ADMIN0 MAPPINGS (same connection)
            # ============================================================
            admin0_inserted = 0
            if country_code:
                cur.execute("""
                    CREATE TEMP TABLE h3_admin0_staging (
                        h3_index BIGINT,
                        iso3 VARCHAR(3)
                    ) ON COMMIT DROP
                """)

                buffer2 = StringIO()
                for cell in cells:
                    buffer2.write(f"{cell['h3_index']}\t{country_code}\n")

                buffer2.seek(0)
                with cur.copy("COPY h3_admin0_staging (h3_index, iso3) FROM STDIN") as copy:
                    copy.write(buffer2.read())

                cur.execute("""
                    INSERT INTO h3.cell_admin0 (h3_index, iso3)
                    SELECT h3_index, iso3
                    FROM h3_admin0_staging
                    ON CONFLICT (h3_index, iso3) DO NOTHING
                """)

                admin0_inserted = cur.rowcount
                logger.debug(f"   Admin0 mappings inserted: {admin0_inserted:,}")

        conn.commit()

    return rows_inserted, admin0_inserted
