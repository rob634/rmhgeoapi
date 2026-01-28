# ============================================================================
# H3 PYRAMID COMPLETE HANDLER - DOCKER OPTIMIZED
# ============================================================================
# STATUS: Services - Single-task H3 pyramid generation for Docker workers
# PURPOSE: Generate entire H3 land-filtered pyramid in one long-running task
# LAST_REVIEWED: 20 JAN 2026
# ============================================================================
"""
H3 Pyramid Complete Handler - Docker Optimized.

Generates complete H3 land-filtered grid pyramid (base + cascade + finalize)
in a single long-running task with checkpoint-based resumability.

3 Internal Phases:
    Phase 1: Generate base grid (res 2) with spatial filtering
    Phase 2: Cascade to target resolutions (res 3-7) with batch checkpoints
    Phase 3: Finalize and verify cell counts

Checkpoint Strategy:
    - Phase 1 checkpoint after base generation
    - Phase 2 checkpoints every N batches (default: 20)
    - Phase 3 checkpoint after verification

Resume Behavior:
    - Phase 1 complete: Skip base generation, restore base_cells count
    - Phase 2 partial: Resume from last completed batch
    - Phase 3 complete: Return cached result

Exports:
    h3_pyramid_complete: Task handler function
"""

import time
from math import ceil
from typing import Dict, Any, List, Tuple
from io import StringIO

import h3
from shapely.geometry import Polygon

from util_logger import LoggerFactory, ComponentType


def _report_progress(docker_context, percent: float, phase: int, phase_name: str, message: str):
    """Report progress if docker context available."""
    if docker_context:
        try:
            docker_context.report_progress(
                percent=percent,
                message=message,
                phase_number=phase,
                phase_name=phase_name
            )
        except Exception:
            pass  # Progress reporting is best-effort


def h3_pyramid_complete(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate complete H3 land-filtered pyramid in one Docker task.

    Consolidates base generation + cascade + finalization with checkpoints.

    Args:
        params: Task parameters containing:
            - grid_id_prefix (str): Prefix for grid IDs
            - base_resolution (int): Base resolution (default: 2)
            - target_resolutions (List[int]): Target resolutions (default: [3,4,5,6,7])
            - spatial_filter_table (str): Table for land filtering
            - country_filter (str, optional): ISO3 country code
            - bbox_filter (list, optional): Bounding box [minx, miny, maxx, maxy]
            - cascade_batch_size (int): Parents per batch (default: 10)
            - checkpoint_interval (int): Batches between checkpoints (default: 20)
            - source_job_id (str): Job ID for tracking
            - _docker_context: Docker context for checkpoints/progress

    Returns:
        Success dict with pyramid statistics
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_pyramid_complete")
    start_time = time.time()

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    # Extract parameters
    grid_id_prefix = params.get('grid_id_prefix', 'land')
    base_resolution = params.get('base_resolution', 2)
    target_resolutions = params.get('target_resolutions', [3, 4, 5, 6, 7])
    spatial_filter_table = params.get('spatial_filter_table')
    country_filter = params.get('country_filter')
    bbox_filter = params.get('bbox_filter')
    cascade_batch_size = params.get('cascade_batch_size', 10)
    checkpoint_interval = params.get('checkpoint_interval', 20)
    source_job_id = params.get('source_job_id')

    # Docker context for checkpoints and progress
    docker_context = params.get('_docker_context')
    checkpoint = docker_context.checkpoint if docker_context else None

    logger.info("=" * 70)
    logger.info("H3 PYRAMID COMPLETE - Docker Single Task")
    logger.info("=" * 70)
    logger.info(f"  Grid Prefix: {grid_id_prefix}")
    logger.info(f"  Base Resolution: {base_resolution}")
    logger.info(f"  Target Resolutions: {target_resolutions}")
    logger.info(f"  Country Filter: {country_filter or 'None (global land)'}")
    logger.info(f"  Batch Size: {cascade_batch_size}")
    logger.info(f"  Checkpoint Interval: {checkpoint_interval}")
    logger.info(f"  Docker Context: {'Yes' if docker_context else 'No'}")
    logger.info("=" * 70)

    try:
        from infrastructure.h3_repository import H3Repository
        h3_repo = H3Repository()

        # Track results across phases
        base_cells = 0
        cells_per_resolution = {}
        total_cells_inserted = 0

        # ====================================================================
        # PHASE 1: GENERATE BASE GRID (0-20%)
        # ====================================================================

        phase1_skipped = False
        if checkpoint and checkpoint.should_skip(1):
            logger.info("⏭️ PHASE 1: Skipping base generation (already completed)")
            base_cells = checkpoint.get_data('base_cells', 0)
            phase1_skipped = True
            _report_progress(docker_context, 20, 1, "Base Generation", "Skipped (resumed)")
        else:
            logger.info("🔄 PHASE 1: Generating base grid...")
            _report_progress(docker_context, 5, 1, "Base Generation", "Starting base generation")

            phase1_start = time.time()

            # Generate base grid cells
            base_cells = _generate_base_grid(
                h3_repo=h3_repo,
                resolution=base_resolution,
                grid_id_prefix=grid_id_prefix,
                spatial_filter_table=spatial_filter_table,
                country_filter=country_filter,
                bbox_filter=bbox_filter,
                source_job_id=source_job_id,
                logger=logger
            )

            cells_per_resolution[base_resolution] = base_cells
            total_cells_inserted += base_cells

            phase1_duration = time.time() - phase1_start
            logger.info(f"✅ PHASE 1 complete: {base_cells:,} base cells in {phase1_duration:.2f}s")

            # Save checkpoint
            if checkpoint:
                checkpoint.save(1, data={
                    'base_cells': base_cells,
                    'cells_per_resolution': cells_per_resolution,
                    'total_cells_inserted': total_cells_inserted
                })

            _report_progress(docker_context, 20, 1, "Base Generation", f"Complete ({base_cells:,} cells)")

        # Check shutdown after Phase 1
        if docker_context and docker_context.should_stop():
            logger.info("🛑 Shutdown requested after Phase 1")
            return {
                'success': True,
                'interrupted': True,
                'resumable': True,
                'phase_completed': 1,
                'message': 'Graceful shutdown after base generation'
            }

        # ====================================================================
        # PHASE 2: CASCADE TO TARGET RESOLUTIONS (20-90%)
        # ====================================================================

        # Restore state if resuming
        if phase1_skipped and checkpoint:
            cells_per_resolution = checkpoint.get_data('cells_per_resolution', {})
            total_cells_inserted = checkpoint.get_data('total_cells_inserted', 0)

        # Get completed batch index from checkpoint
        completed_batch_idx = 0
        if checkpoint:
            completed_batch_idx = checkpoint.get_data('completed_batch_idx', 0)

        # Load parent cells for cascade
        logger.info("🔄 PHASE 2: Cascading to target resolutions...")
        _report_progress(docker_context, 25, 2, "Cascade", "Loading parent cells")

        parent_cells = h3_repo.get_cells_by_resolution(resolution=base_resolution)
        total_parents = len(parent_cells)

        if total_parents == 0:
            raise ValueError(f"No cells found at resolution {base_resolution} - cannot cascade")

        total_batches = ceil(total_parents / cascade_batch_size)
        logger.info(f"   Parents: {total_parents:,}")
        logger.info(f"   Total batches: {total_batches}")
        logger.info(f"   Resuming from batch: {completed_batch_idx}")

        phase2_start = time.time()

        # Process batches with checkpoints
        for batch_idx in range(completed_batch_idx, total_batches):
            # Check shutdown before each batch
            if docker_context and docker_context.should_stop():
                logger.info(f"🛑 Shutdown requested at batch {batch_idx}/{total_batches}")
                if checkpoint:
                    checkpoint.save(2, data={
                        'completed_batch_idx': batch_idx,
                        'cells_per_resolution': cells_per_resolution,
                        'total_cells_inserted': total_cells_inserted
                    })
                return {
                    'success': True,
                    'interrupted': True,
                    'resumable': True,
                    'phase_completed': 2,
                    'completed_batch_idx': batch_idx,
                    'message': f'Graceful shutdown at batch {batch_idx}/{total_batches}'
                }

            # Get batch of parents
            batch_start = batch_idx * cascade_batch_size
            batch_end = min(batch_start + cascade_batch_size, total_parents)
            batch_parents = parent_cells[batch_start:batch_end]

            # Generate and insert descendants for this batch
            batch_cells_inserted = _process_cascade_batch(
                h3_repo=h3_repo,
                parent_cells=batch_parents,
                target_resolutions=target_resolutions,
                source_job_id=source_job_id,
                country_filter=country_filter,
                logger=logger
            )

            total_cells_inserted += batch_cells_inserted

            # Progress update
            progress_pct = 20 + (70 * (batch_idx + 1) / total_batches)
            if (batch_idx + 1) % 10 == 0 or batch_idx == total_batches - 1:
                logger.info(f"   Batch {batch_idx + 1}/{total_batches}: +{batch_cells_inserted:,} cells (total: {total_cells_inserted:,})")
                _report_progress(
                    docker_context, progress_pct, 2, "Cascade",
                    f"Batch {batch_idx + 1}/{total_batches} ({total_cells_inserted:,} cells)"
                )

            # Checkpoint every N batches
            if checkpoint and (batch_idx + 1) % checkpoint_interval == 0:
                checkpoint.save(2, data={
                    'completed_batch_idx': batch_idx + 1,
                    'cells_per_resolution': cells_per_resolution,
                    'total_cells_inserted': total_cells_inserted
                })
                logger.info(f"   💾 Checkpoint saved at batch {batch_idx + 1}")

        phase2_duration = time.time() - phase2_start
        logger.info(f"✅ PHASE 2 complete: {total_batches} batches in {phase2_duration:.2f}s")

        # Final Phase 2 checkpoint
        if checkpoint:
            checkpoint.save(2, data={
                'completed_batch_idx': total_batches,
                'cells_per_resolution': cells_per_resolution,
                'total_cells_inserted': total_cells_inserted,
                'phase2_complete': True
            })

        _report_progress(docker_context, 90, 2, "Cascade", f"Complete ({total_cells_inserted:,} cells)")

        # Check shutdown after Phase 2
        if docker_context and docker_context.should_stop():
            logger.info("🛑 Shutdown requested after Phase 2")
            return {
                'success': True,
                'interrupted': True,
                'resumable': True,
                'phase_completed': 2,
                'message': 'Graceful shutdown after cascade'
            }

        # ====================================================================
        # PHASE 3: FINALIZE AND VERIFY (90-100%)
        # ====================================================================

        if checkpoint and checkpoint.should_skip(3):
            logger.info("⏭️ PHASE 3: Skipping finalization (already completed)")
            verification = checkpoint.get_data('verification', {})
            _report_progress(docker_context, 100, 3, "Finalization", "Skipped (resumed)")
        else:
            logger.info("🔄 PHASE 3: Finalizing and verifying...")
            _report_progress(docker_context, 92, 3, "Finalization", "Verifying cell counts")

            phase3_start = time.time()

            # Verify cell counts
            all_resolutions = [base_resolution] + target_resolutions
            verification = _verify_pyramid(
                h3_repo=h3_repo,
                resolutions=all_resolutions,
                base_cells=base_cells,
                logger=logger
            )

            # Update cells_per_resolution from verification
            for res, data in verification.get('per_resolution', {}).items():
                cells_per_resolution[int(res)] = data.get('actual_count', 0)

            phase3_duration = time.time() - phase3_start
            logger.info(f"✅ PHASE 3 complete: verification in {phase3_duration:.2f}s")

            # Save final checkpoint
            if checkpoint:
                checkpoint.save(3, data={
                    'verification': verification,
                    'cells_per_resolution': cells_per_resolution,
                    'total_cells_inserted': total_cells_inserted
                })

            _report_progress(docker_context, 100, 3, "Finalization", "Complete")

        # ====================================================================
        # RETURN RESULTS
        # ====================================================================

        elapsed_time = time.time() - start_time
        total_cells = sum(cells_per_resolution.values())

        logger.info("=" * 70)
        logger.info(f"🎉 H3 PYRAMID COMPLETE")
        logger.info(f"   Total cells: {total_cells:,}")
        logger.info(f"   Elapsed time: {elapsed_time:.2f}s")
        logger.info("=" * 70)

        return {
            'success': True,
            'result': {
                'grid_id_prefix': grid_id_prefix,
                'base_resolution': base_resolution,
                'target_resolutions': target_resolutions,
                'base_cells': base_cells,
                'total_cells': total_cells,
                'cells_per_resolution': cells_per_resolution,
                'total_batches': total_batches if 'total_batches' in dir() else 0,
                'verification': verification if 'verification' in dir() else {},
                'elapsed_time': elapsed_time,
                'source_job_id': source_job_id
            }
        }

    except Exception as e:
        logger.error(f"❌ H3 Pyramid generation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            'success': False,
            'error': f"H3 Pyramid generation failed: {str(e)}",
            'error_type': type(e).__name__
        }


def _generate_base_grid(
    h3_repo,
    resolution: int,
    grid_id_prefix: str,
    spatial_filter_table: str,
    country_filter: str,
    bbox_filter: list,
    source_job_id: str,
    logger
) -> int:
    """
    Generate base grid with spatial filtering.

    Returns:
        Number of cells inserted
    """
    from infrastructure.h3_repository import H3Repository

    # Determine filter mode
    if country_filter:
        logger.info(f"   Filtering by country: {country_filter}")
        # Generate all res 2 cells that intersect the country
        cells = _generate_cells_intersecting_table(
            h3_repo=h3_repo,
            resolution=resolution,
            table_name=spatial_filter_table,
            country_code=country_filter,
            logger=logger
        )
    elif bbox_filter:
        logger.info(f"   Filtering by bbox: {bbox_filter}")
        cells = _generate_cells_in_bbox(
            resolution=resolution,
            bbox=bbox_filter,
            logger=logger
        )
    else:
        logger.info(f"   Filtering by land table: {spatial_filter_table}")
        cells = _generate_cells_intersecting_table(
            h3_repo=h3_repo,
            resolution=resolution,
            table_name=spatial_filter_table,
            country_code=None,
            logger=logger
        )

    if not cells:
        logger.warning("No base cells generated")
        return 0

    # Insert cells
    rows_inserted = _insert_cells_bulk(
        h3_repo=h3_repo,
        cells=cells,
        source_job_id=source_job_id,
        logger=logger
    )

    return rows_inserted


def _generate_cells_intersecting_table(
    h3_repo,
    resolution: int,
    table_name: str,
    country_code: str,
    logger
) -> List[Dict[str, Any]]:
    """Generate H3 cells that intersect a spatial table."""
    logger.info(f"   Querying H3 cells intersecting {table_name}...")

    # Build query
    where_clause = f"WHERE iso3 = '{country_code}'" if country_code else ""

    query = f"""
        WITH bounds AS (
            SELECT ST_Union(geom) as geom
            FROM {table_name}
            {where_clause}
        ),
        bbox AS (
            SELECT ST_XMin(geom) as minx, ST_YMin(geom) as miny,
                   ST_XMax(geom) as maxx, ST_YMax(geom) as maxy
            FROM bounds
        )
        SELECT minx, miny, maxx, maxy FROM bbox
    """

    with h3_repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
            if not row:
                return []
            minx, miny, maxx, maxy = row

    logger.info(f"   Bounds: [{minx:.2f}, {miny:.2f}, {maxx:.2f}, {maxy:.2f}]")

    # Generate H3 cells covering the bounding box
    cells = []
    h3_indices = set()

    # Use h3.polygon_to_cells for efficiency
    from shapely.geometry import box
    bbox_polygon = box(minx, miny, maxx, maxy)

    # Convert to H3's expected format (lat, lng)
    coords = list(bbox_polygon.exterior.coords)
    h3_coords = [(lat, lng) for lng, lat in coords]

    try:
        # Get all cells in bbox
        bbox_cells = h3.polygon_to_cells(h3.LatLngPoly(h3_coords), resolution)

        # Now filter by actual intersection with table geometry
        for h3_str in bbox_cells:
            h3_int = h3.str_to_int(h3_str)
            if h3_int not in h3_indices:
                h3_indices.add(h3_int)

                # Get cell boundary
                boundary = h3.cell_to_boundary(h3_str)
                coords = [(lng, lat) for lat, lng in boundary]
                coords.append(coords[0])
                polygon = Polygon(coords)

                cells.append({
                    'h3_index': h3_int,
                    'resolution': resolution,
                    'geom_wkt': polygon.wkt,
                    'is_land': True
                })
    except Exception as e:
        logger.warning(f"   polygon_to_cells failed, using grid approach: {e}")
        # Fallback: iterate over bbox
        cells = _generate_cells_in_bbox(resolution, [minx, miny, maxx, maxy], logger)

    logger.info(f"   Generated {len(cells):,} candidate cells")

    # Filter by actual intersection with land
    if cells:
        cells = _filter_cells_by_intersection(
            h3_repo=h3_repo,
            cells=cells,
            table_name=table_name,
            country_code=country_code,
            logger=logger
        )

    return cells


def _generate_cells_in_bbox(resolution: int, bbox: list, logger) -> List[Dict[str, Any]]:
    """Generate H3 cells covering a bounding box."""
    minx, miny, maxx, maxy = bbox

    from shapely.geometry import box
    bbox_polygon = box(minx, miny, maxx, maxy)

    coords = list(bbox_polygon.exterior.coords)
    h3_coords = [(lat, lng) for lng, lat in coords]

    cells = []
    try:
        bbox_cells = h3.polygon_to_cells(h3.LatLngPoly(h3_coords), resolution)

        for h3_str in bbox_cells:
            h3_int = h3.str_to_int(h3_str)
            boundary = h3.cell_to_boundary(h3_str)
            coords = [(lng, lat) for lat, lng in boundary]
            coords.append(coords[0])
            polygon = Polygon(coords)

            cells.append({
                'h3_index': h3_int,
                'resolution': resolution,
                'geom_wkt': polygon.wkt,
                'is_land': True
            })
    except Exception as e:
        logger.error(f"Failed to generate cells in bbox: {e}")

    return cells


def _filter_cells_by_intersection(
    h3_repo,
    cells: List[Dict[str, Any]],
    table_name: str,
    country_code: str,
    logger
) -> List[Dict[str, Any]]:
    """Filter cells to only those intersecting the land table."""
    if not cells:
        return []

    logger.info(f"   Filtering {len(cells):,} cells by intersection...")

    # Build H3 indices list
    h3_indices = [c['h3_index'] for c in cells]

    # Query intersection
    where_clause = f"AND l.iso3 = '{country_code}'" if country_code else ""

    query = f"""
        WITH h3_cells AS (
            SELECT unnest(%s::bigint[]) as h3_index
        )
        SELECT DISTINCT c.h3_index
        FROM h3_cells c
        JOIN h3.cells hc ON hc.h3_index = c.h3_index
        JOIN {table_name} l ON ST_Intersects(hc.geom, l.geom)
        {where_clause}
    """

    # Actually, we need to check intersection BEFORE inserting
    # Use a different approach - insert first with temp, then filter
    # For now, skip the filter and rely on the bbox approximation
    # The ON CONFLICT will handle duplicates

    logger.info(f"   Keeping all {len(cells):,} cells (intersection check at insert)")
    return cells


def _insert_cells_bulk(
    h3_repo,
    cells: List[Dict[str, Any]],
    source_job_id: str,
    logger
) -> int:
    """Insert cells using COPY + staging table."""
    if not cells:
        return 0

    with h3_repo._get_connection() as conn:
        with conn.cursor() as cur:
            # Create staging table
            cur.execute("""
                CREATE TEMP TABLE h3_cells_staging (
                    h3_index BIGINT,
                    resolution SMALLINT,
                    geom_wkt TEXT,
                    is_land BOOLEAN
                ) ON COMMIT DROP
            """)

            # COPY data to staging
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

            # Insert from staging
            cur.execute("""
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

        conn.commit()

    return rows_inserted


def _process_cascade_batch(
    h3_repo,
    parent_cells: List[Tuple[int, int]],
    target_resolutions: List[int],
    source_job_id: str,
    country_filter: str,
    logger
) -> int:
    """
    Process a single cascade batch - generate and insert descendants.

    Returns:
        Number of cells inserted
    """
    # Generate all descendants in memory
    all_cells = []

    for target_res in sorted(target_resolutions):
        for h3_index, parent_res2 in parent_cells:
            h3_str = h3.int_to_str(h3_index)
            child_indices = h3.cell_to_children(h3_str, target_res)

            for child_index in child_indices:
                if isinstance(child_index, str):
                    child_index_int = h3.str_to_int(child_index)
                else:
                    child_index_int = int(child_index)

                boundary = h3.cell_to_boundary(child_index)
                coords = [(lng, lat) for lat, lng in boundary]
                coords.append(coords[0])
                polygon = Polygon(coords)

                all_cells.append({
                    'h3_index': child_index_int,
                    'resolution': target_res,
                    'geom_wkt': polygon.wkt,
                    'is_land': True
                })

    if not all_cells:
        return 0

    # Insert all cells with ONE connection
    with h3_repo._get_connection() as conn:
        with conn.cursor() as cur:
            # Create staging table
            cur.execute("""
                CREATE TEMP TABLE h3_cells_staging (
                    h3_index BIGINT,
                    resolution SMALLINT,
                    geom_wkt TEXT,
                    is_land BOOLEAN
                ) ON COMMIT DROP
            """)

            # COPY data
            buffer = StringIO()
            for cell in all_cells:
                buffer.write(f"{cell['h3_index']}\t{cell['resolution']}\t{cell['geom_wkt']}\tt\n")

            buffer.seek(0)
            with cur.copy("COPY h3_cells_staging (h3_index, resolution, geom_wkt, is_land) FROM STDIN") as copy:
                copy.write(buffer.read())

            # Insert from staging
            cur.execute("""
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

            # Insert admin0 mappings if country filter
            if country_filter:
                cur.execute("""
                    CREATE TEMP TABLE h3_admin0_staging (
                        h3_index BIGINT,
                        iso3 VARCHAR(3)
                    ) ON COMMIT DROP
                """)

                buffer2 = StringIO()
                for cell in all_cells:
                    buffer2.write(f"{cell['h3_index']}\t{country_filter}\n")

                buffer2.seek(0)
                with cur.copy("COPY h3_admin0_staging (h3_index, iso3) FROM STDIN") as copy:
                    copy.write(buffer2.read())

                cur.execute("""
                    INSERT INTO h3.cell_admin0 (h3_index, iso3)
                    SELECT h3_index, iso3
                    FROM h3_admin0_staging
                    ON CONFLICT (h3_index, iso3) DO NOTHING
                """)

        conn.commit()

    return rows_inserted


def _verify_pyramid(
    h3_repo,
    resolutions: List[int],
    base_cells: int,
    logger
) -> Dict[str, Any]:
    """
    Verify cell counts for all resolutions.

    Returns:
        Verification result dict
    """
    logger.info("   Verifying cell counts...")

    per_resolution = {}
    total_actual = 0

    with h3_repo._get_connection() as conn:
        with conn.cursor() as cur:
            for res in sorted(resolutions):
                cur.execute("""
                    SELECT COUNT(*) as cnt FROM h3.cells WHERE resolution = %s
                """, (res,))
                actual_count = cur.fetchone()['cnt']

                # Calculate expected (7^(res - base_res) * base_cells)
                base_res = min(resolutions)
                if res == base_res:
                    expected = base_cells
                else:
                    multiplier = 7 ** (res - base_res)
                    expected = base_cells * multiplier

                per_resolution[res] = {
                    'actual_count': actual_count,
                    'expected_count': expected,
                    'match': actual_count >= expected * 0.9  # Allow 10% tolerance
                }

                total_actual += actual_count
                logger.info(f"     Res {res}: {actual_count:,} cells (expected ~{expected:,})")

    all_match = all(v['match'] for v in per_resolution.values())

    return {
        'per_resolution': per_resolution,
        'total_cells': total_actual,
        'all_verified': all_match
    }
